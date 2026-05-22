package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	"github.com/apple/fdb-joshua/k8s/agent-scaler/internal/config"
	"github.com/apple/fdb-joshua/k8s/agent-scaler/internal/joshua"
	"github.com/apple/fdb-joshua/k8s/agent-scaler/internal/scaler"
)

func main() {
	ctrl.SetLogger(zap.New())
	log := ctrl.Log.WithName("agent-scaler")

	cfg, err := config.Load()
	if err != nil {
		log.Error(err, "loading config")
		os.Exit(1)
	}

	scheme := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(scheme); err != nil {
		log.Error(err, "adding client-go scheme")
		os.Exit(1)
	}
	if err := batchv1.AddToScheme(scheme); err != nil {
		log.Error(err, "adding batchv1 scheme")
		os.Exit(1)
	}
	if err := corev1.AddToScheme(scheme); err != nil {
		log.Error(err, "adding corev1 scheme")
		os.Exit(1)
	}

	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{
		Scheme: scheme,
		Metrics: metricsserver.Options{
			BindAddress: cfg.MetricsAddr,
		},
		HealthProbeBindAddress: cfg.HealthAddr,
		LeaderElection:         false,
	})
	if err != nil {
		log.Error(err, "creating manager")
		os.Exit(1)
	}

	counter, err := joshua.NewEnsembleCounter(cfg.FDBClusterFile, cfg.JoshuaNamespace)
	if err != nil {
		log.Error(err, "opening FDB connection")
		os.Exit(1)
	}
	s := scaler.New(cfg, mgr.GetClient(), counter, log.WithName("scaler"))

	if err := mgr.Add(s); err != nil {
		log.Error(err, "adding scaler to manager")
		os.Exit(1)
	}

	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		log.Error(err, "adding healthz check")
		os.Exit(1)
	}
	if err := mgr.AddReadyzCheck("readyz", func(_ *http.Request) error {
		if !s.IsReady() {
			return fmt.Errorf("not ready")
		}
		return nil
	}); err != nil {
		log.Error(err, "adding readyz check")
		os.Exit(1)
	}

	log.Info("starting agent-scaler",
		"agentName", cfg.AgentName,
		"maxJobs", cfg.MaxJobs,
		"batchSize", cfg.BatchSize,
		"checkDelay", cfg.CheckDelay,
		"namespace", cfg.Namespace,
	)

	// SIGKILL cannot be intercepted — the OS delivers it unconditionally.
	// We handle SIGTERM (Kubernetes graceful stop) and SIGINT (Ctrl-C).
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()

	go func() {
		<-ctx.Done()
		log.Info("shutdown signal received, draining")
	}()

	if err := mgr.Start(ctx); err != nil {
		log.Error(err, "manager exited")
		os.Exit(1)
	}
}
