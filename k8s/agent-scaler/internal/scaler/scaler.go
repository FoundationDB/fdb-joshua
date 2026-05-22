package scaler

import (
	"context"
	"fmt"
	"os"
	"strings"
	"sync/atomic"
	"time"

	"github.com/apple/fdb-joshua/k8s/agent-scaler/internal/config"
	"github.com/apple/fdb-joshua/k8s/agent-scaler/internal/joshua"
	"github.com/go-logr/logr"
	"github.com/prometheus/client_golang/prometheus"
	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	ctrlmetrics "sigs.k8s.io/controller-runtime/pkg/metrics"
	"sigs.k8s.io/yaml"

	"sigs.k8s.io/controller-runtime/pkg/client"
)

var (
	metricPendingEnsembles = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "joshua_pending_ensembles",
		Help: "Number of pending ensembles in the FDB queue.",
	})
	metricActiveJobs = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "joshua_active_jobs",
		Help: "Total active Joshua jobs of any type.",
	})
	metricProtectedFailedJobs = prometheus.NewGauge(prometheus.GaugeOpts{
		Name: "joshua_protected_failed_jobs",
		Help: "Number of failed jobs protected from cleanup (less than 1 day old).",
	})
	metricJobsCreated = prometheus.NewCounter(prometheus.CounterOpts{
		Name: "joshua_jobs_created_total",
		Help: "Total number of Joshua jobs created.",
	})
	metricJobsDeleted = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "joshua_jobs_deleted_total",
		Help: "Total number of Joshua jobs deleted.",
	}, []string{"reason"})
	metricJobsCapped = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "joshua_jobs_capped_total",
		Help: "Times job creation was capped.",
	}, []string{"reason"})
	metricReconcileDuration = prometheus.NewHistogram(prometheus.HistogramOpts{
		Name:    "joshua_reconcile_duration_seconds",
		Help:    "Duration of each reconcile loop iteration.",
		Buckets: prometheus.DefBuckets,
	})
	metricReconcileErrors = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "joshua_reconcile_errors_total",
		Help: "Total reconcile errors by source.",
	}, []string{"source"})
)

func init() {
	ctrlmetrics.Registry.MustRegister(
		metricPendingEnsembles,
		metricActiveJobs,
		metricProtectedFailedJobs,
		metricJobsCreated,
		metricJobsDeleted,
		metricJobsCapped,
		metricReconcileDuration,
		metricReconcileErrors,
	)
}

// Scaler implements ctrl.Runnable and manages Joshua agent job scaling.
type Scaler struct {
	cfg    *config.Config
	client client.Client
	fdb    joshua.EnsembleCounter
	log    logr.Logger
	ready  atomic.Bool
}

// New creates a Scaler. The caller must register it with mgr.Add().
func New(cfg *config.Config, c client.Client, counter joshua.EnsembleCounter, log logr.Logger) *Scaler {
	return &Scaler{
		cfg:    cfg,
		client: c,
		fdb:    counter,
		log:    log,
	}
}

// IsReady reports whether the scaler has finished its boot sequence.
func (s *Scaler) IsReady() bool {
	return s.ready.Load()
}

// Start implements ctrl.Runnable.
func (s *Scaler) Start(ctx context.Context) error {
	if s.cfg.RestartAgentsOnBoot {
		if err := s.labelPodsLastTest(ctx); err != nil {
			s.log.Error(err, "labeling pods on boot")
		}
	}
	s.ready.Store(true)

	ticker := time.NewTicker(s.cfg.CheckDelay)
	defer ticker.Stop()

	// Run one iteration immediately, then follow the ticker.
	if err := s.reconcile(ctx); err != nil {
		s.log.Error(err, "reconcile failed")
	}

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
			if err := s.reconcile(ctx); err != nil {
				s.log.Error(err, "reconcile failed")
			}
		}
	}
}

func (s *Scaler) reconcile(ctx context.Context) error {
	start := time.Now()
	defer func() { metricReconcileDuration.Observe(time.Since(start).Seconds()) }()

	jobs, err := s.listAllJobs(ctx)
	if err != nil {
		metricReconcileErrors.WithLabelValues("k8s").Inc()
		return fmt.Errorf("listing jobs: %w", err)
	}

	protected := s.buildProtectedSet(jobs)
	metricProtectedFailedJobs.Set(float64(len(protected)))
	if len(protected) > 0 {
		s.log.Info("protecting failed jobs", "count", len(protected), "agentName", s.cfg.AgentName)
	}

	if !s.cfg.UseK8sTTLController {
		if err := s.cleanupCompleted(ctx, jobs, protected); err != nil {
			metricReconcileErrors.WithLabelValues("k8s").Inc()
			s.log.Error(err, "cleanup completed jobs")
		}
		if err := s.cleanupCompletedPods(ctx, protected); err != nil {
			metricReconcileErrors.WithLabelValues("k8s").Inc()
			s.log.Error(err, "cleanup completed pods")
		}
	}

	if err := s.cleanupExpiredFailed(ctx, jobs, protected); err != nil {
		metricReconcileErrors.WithLabelValues("k8s").Inc()
		s.log.Error(err, "cleanup expired failed jobs")
	}

	pending, err := s.fdb.CountPendingEnsembles(ctx)
	if err != nil {
		metricReconcileErrors.WithLabelValues("fdb").Inc()
		s.log.Error(err, "counting pending ensembles")
		pending = 0
	}
	metricPendingEnsembles.Set(float64(pending))
	s.log.Info("ensemble queue", "pending", pending)

	activeJobs := countAllActiveJobs(jobs)
	metricActiveJobs.Set(float64(activeJobs))
	s.log.Info("active jobs", "active", activeJobs, "maxJobs", s.cfg.MaxJobs)

	if pending > 0 && activeJobs < s.cfg.MaxJobs {
		if err := s.provision(ctx, pending, activeJobs); err != nil {
			metricReconcileErrors.WithLabelValues("k8s").Inc()
			s.log.Error(err, "provisioning jobs")
		}
	}

	return nil
}

// buildProtectedSet returns job names that are failed AND less than 1 day old.
func (s *Scaler) buildProtectedSet(jobs []batchv1.Job) map[string]struct{} {
	protected := make(map[string]struct{})
	cutoff := time.Now().Add(-24 * time.Hour)
	for _, job := range jobs {
		if !isFailedJob(job) {
			continue
		}
		if job.CreationTimestamp.After(cutoff) {
			protected[job.Name] = struct{}{}
		}
	}

	return protected
}

func (s *Scaler) cleanupCompleted(ctx context.Context, jobs []batchv1.Job, protected map[string]struct{}) error {
	for _, job := range jobs {
		if _, skip := protected[job.Name]; skip {
			continue
		}
		if job.Status.Succeeded == 1 && job.Status.Failed == 0 && job.Status.Active == 0 {
			s.log.Info("deleting completed job (1/1)", "job", job.Name)
			err := s.client.Delete(ctx, &job)
			if err != nil && k8serrors.IsNotFound(err) {
				return fmt.Errorf("deleting completed job %s: %w", job.Name, err)
			}
			metricJobsDeleted.WithLabelValues("completed").Inc()
		}
	}

	return nil
}

func (s *Scaler) cleanupCompletedPods(ctx context.Context, protected map[string]struct{}) error {
	var pods corev1.PodList
	if err := s.client.List(ctx, &pods, client.InNamespace(s.cfg.Namespace), client.MatchingLabels(map[string]string{"app": "joshua-agent"})); err != nil {
		return fmt.Errorf("listing pods: %w", err)
	}

	deleted := make(map[string]struct{})
	for _, pod := range pods.Items {
		phase := pod.Status.Phase
		if phase != corev1.PodSucceeded && phase != corev1.PodFailed {
			continue
		}
		jobName := pod.Labels["job-name"]
		if _, skip := protected[jobName]; skip {
			continue
		}
		if _, done := deleted[jobName]; done {
			continue
		}

		s.log.Info("deleting job based on pod phase", "job", jobName, "phase", phase)
		job := &batchv1.Job{}
		if err := s.client.Get(ctx, client.ObjectKey{Name: jobName, Namespace: s.cfg.Namespace}, job); err != nil {
			s.log.Error(err, "getting job for pod-based cleanup", "job", jobName)
			continue
		}
		err := s.client.Delete(ctx, job)
		if err != nil && !k8serrors.IsNotFound(err) {
			return fmt.Errorf("deleting job %s from pod phase: %w", jobName, err)
		}
		deleted[jobName] = struct{}{}
		metricJobsDeleted.WithLabelValues("failed_pod").Inc()
	}

	return nil
}

func (s *Scaler) cleanupExpiredFailed(ctx context.Context, jobs []batchv1.Job, protected map[string]struct{}) error {
	for _, job := range jobs {
		if !isFailedJob(job) {
			continue
		}
		if _, prot := protected[job.Name]; prot {
			continue
		}
		s.log.Info("deleting expired failed job", "job", job.Name)
		err := s.client.Delete(ctx, &job)
		if err != nil && !k8serrors.IsNotFound(err) {
			return fmt.Errorf("deleting expired failed job %s: %w", job.Name, err)
		}
		metricJobsDeleted.WithLabelValues("expired_failed").Inc()
	}

	return nil
}

func (s *Scaler) provision(ctx context.Context, pending, activeJobs int) error {
	slotsAvailable := s.cfg.MaxJobs - activeJobs
	bs := s.cfg.BatchSize
	if bs <= 0 {
		bs = 1
	}
	numToCreate := (pending + bs - 1) / bs

	if numToCreate > slotsAvailable {
		metricJobsCapped.WithLabelValues("max_jobs").Inc()
		numToCreate = slotsAvailable
	}

	if s.cfg.MaxNewJobs > 0 {
		if pending > 1000 {
			if numToCreate > 1000 {
				metricJobsCapped.WithLabelValues("large_queue").Inc()
				numToCreate = 1000
			}
		} else {
			if numToCreate > s.cfg.MaxNewJobs {
				metricJobsCapped.WithLabelValues("max_new_jobs").Inc()
				numToCreate = s.cfg.MaxNewJobs
			}
		}
	}

	if numToCreate <= 0 {
		return nil
	}

	s.log.Info("provisioning jobs", "count", numToCreate, "pending", pending)

	tmplBytes, err := os.ReadFile(s.cfg.TemplatePath)
	if err != nil {
		return fmt.Errorf("reading template %s: %w", s.cfg.TemplatePath, err)
	}

	suffix := time.Now().Format("060102150405")
	for i := 0; i < numToCreate; i++ {
		jobSuffix := fmt.Sprintf("%s-%d", suffix, i)
		replacer := strings.NewReplacer("${JOBNAME_SUFFIX}", jobSuffix, "${AGENT_TAG}", s.cfg.AgentTag)
		rendered := replacer.Replace(string(tmplBytes))

		var job batchv1.Job
		if err := yaml.Unmarshal([]byte(rendered), &job); err != nil {
			return fmt.Errorf("unmarshaling job template: %w", err)
		}
		job.Name = fmt.Sprintf("%s-%s", s.cfg.AgentName, jobSuffix)
		job.Namespace = s.cfg.Namespace

		if err := s.client.Create(ctx, &job); err != nil {
			return fmt.Errorf("creating job %s: %w", job.Name, err)
		}
		metricJobsCreated.Inc()
		s.log.Info("created job", "job", job.Name)
	}
	return nil
}

func (s *Scaler) labelPodsLastTest(ctx context.Context) error {
	var pods corev1.PodList
	if err := s.client.List(ctx, &pods,
		client.InNamespace(s.cfg.Namespace),
		client.MatchingLabels{"app": "joshua-agent"},
	); err != nil {
		return fmt.Errorf("listing pods for boot label: %w", err)
	}
	for _, pod := range pods.Items {
		patch := client.MergeFrom(pod.DeepCopy())
		if pod.Labels == nil {
			pod.Labels = make(map[string]string)
		}
		pod.Labels["last_test"] = "true"
		if err := s.client.Patch(ctx, &pod, patch); err != nil {
			s.log.Error(err, "patching pod last_test label", "pod", pod.Name)
		}
	}
	return nil
}

func (s *Scaler) listAllJobs(ctx context.Context) ([]batchv1.Job, error) {
	var list batchv1.JobList

	err := s.client.List(ctx, &list, client.InNamespace(s.cfg.Namespace), client.MatchingLabels(map[string]string{"app": "joshua-agent"}))
	if err != nil {
		return nil, err
	}

	return list.Items, nil
}

func isFailedJob(job batchv1.Job) bool {
	for _, c := range job.Status.Conditions {
		if c.Type == batchv1.JobFailed && c.Status == corev1.ConditionTrue {
			return true
		}
	}
	return false
}

func countAllActiveJobs(jobs []batchv1.Job) int {
	count := 0
	for _, job := range jobs {
		if job.Status.Active > 0 {
			count++
		}
	}
	return count
}
