package config

import (
	"fmt"
	"os"
	"strconv"
	"time"

	"github.com/spf13/pflag"
)

type Config struct {
	BatchSize           int
	MaxJobs             int
	CheckDelay          time.Duration
	MaxNewJobs          int
	UseK8sTTLController bool
	RestartAgentsOnBoot bool
	AgentName           string
	AgentTag            string
	FDBClusterFile      string
	TemplatePath        string
	Namespace           string
	JoshuaNamespace     string
	MetricsAddr         string
	HealthAddr          string
}

// Load parses config from command-line flags, falling back to environment
// variables, then hardcoded defaults. Flag values take precedence.
func Load() (*Config, error) {
	cfg := &Config{}
	fs := pflag.NewFlagSet("agent-scaler", pflag.ContinueOnError)

	fs.IntVar(&cfg.BatchSize, "batch-size", envInt("BATCH_SIZE", 1),
		"Joshua runs each job handles before completing")
	fs.IntVar(&cfg.MaxJobs, "max-jobs", envInt("MAX_JOBS", 10),
		"Global maximum active Joshua jobs of any type")
	fs.DurationVar(&cfg.CheckDelay, "check-delay",
		time.Duration(envInt("CHECK_DELAY", 10))*time.Second,
		"Interval between scaling loop iterations")
	fs.IntVar(&cfg.MaxNewJobs, "max-new-jobs", envInt("MAX_NEW_JOBS", 0),
		"Maximum jobs to create per cycle (0 = unlimited)")
	fs.BoolVar(&cfg.UseK8sTTLController, "use-k8s-ttl-controller",
		envBool("USE_K8S_TTL_CONTROLLER", false),
		"Delegate completed job cleanup to the Kubernetes TTL controller")
	fs.BoolVar(&cfg.RestartAgentsOnBoot, "restart-agents-on-boot",
		envBool("RESTART_AGENTS_ON_BOOT", false),
		"Label existing agent pods to exit after their current test on startup")
	fs.StringVar(&cfg.AgentName, "agent-name", envStr("AGENT_NAME", "joshua-agent"),
		"Name of the Joshua agent to scale (e.g. joshua-agent, joshua-rhel9-agent)")
	fs.StringVar(&cfg.AgentTag, "agent-tag",
		envStr("AGENT_TAG", "foundationdb/joshua-agent:latest"),
		"Docker image tag for agent jobs")
	fs.StringVar(&cfg.FDBClusterFile, "fdb-cluster-file",
		envStr("FDB_CLUSTER_FILE", "/etc/foundationdb/fdb.cluster"),
		"Path to the FoundationDB cluster file")
	fs.StringVar(&cfg.TemplatePath, "template-path",
		envStr("TEMPLATE_PATH", "/template/joshua-agent.yaml.template"),
		"Path to the Job YAML template")
	fs.StringVar(&cfg.JoshuaNamespace, "joshua-namespace",
		envStr("JOSHUA_NAMESPACE", "joshua"),
		"Top-level FDB directory for Joshua")
	fs.StringVar(&cfg.MetricsAddr, "metrics-addr",
		envStr("METRICS_ADDR", ":8080"),
		"Address for the Prometheus metrics endpoint")
	fs.StringVar(&cfg.HealthAddr, "health-addr",
		envStr("HEALTH_ADDR", ":8081"),
		"Address for health and readiness probes")

	if err := fs.Parse(os.Args[1:]); err != nil {
		return nil, fmt.Errorf("parsing flags: %w", err)
	}

	ns, err := readNamespace()
	if err != nil {
		return nil, fmt.Errorf("resolving namespace: %w", err)
	}
	cfg.Namespace = ns

	return cfg, nil
}

func readNamespace() (string, error) {
	data, err := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
	if err == nil {
		return string(data), nil
	}
	if !os.IsNotExist(err) {
		return "", fmt.Errorf("reading service account namespace: %w", err)
	}
	return envStr("NAMESPACE", "joshua"), nil
}

func envStr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	v := os.Getenv(key)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}

func envBool(key string, def bool) bool {
	v := os.Getenv(key)
	if v == "" {
		return def
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		return def
	}
	return b
}
