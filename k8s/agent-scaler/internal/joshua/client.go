package joshua

import (
	"context"
	"encoding/binary"
	"fmt"
	"time"

	"github.com/apple/foundationdb/bindings/go/src/fdb"
	"github.com/apple/foundationdb/bindings/go/src/fdb/directory"
	"github.com/apple/foundationdb/bindings/go/src/fdb/subspace"
	"github.com/apple/foundationdb/bindings/go/src/fdb/tuple"
	"github.com/prometheus/client_golang/prometheus"
	ctrlmetrics "sigs.k8s.io/controller-runtime/pkg/metrics"
)

var fdbQueryDuration = prometheus.NewHistogram(prometheus.HistogramOpts{
	Name:    "joshua_fdb_query_duration_seconds",
	Help:    "Duration of FDB ensemble count queries.",
	Buckets: prometheus.DefBuckets,
})

func init() {
	fdb.MustAPIVersion(710)
	ctrlmetrics.Registry.MustRegister(fdbQueryDuration)
}

// EnsembleCounter returns the number of pending ensemble runs from FDB.
type EnsembleCounter interface {
	CountPendingEnsembles(ctx context.Context) (int, error)
}

type nativeClient struct {
	db              fdb.Database
	joshuaNamespace string
}

// NewEnsembleCounter opens an FDB connection and returns an EnsembleCounter.
func NewEnsembleCounter(clusterFile, joshuaNamespace string) (EnsembleCounter, error) {
	db, err := fdb.OpenDatabase(clusterFile)
	if err != nil {
		return nil, fmt.Errorf("opening FDB: %w", err)
	}
	err = db.Options().SetTransactionTimeout(10000)
	if err != nil {
		return nil, err
	}
	err = db.Options().SetTransactionRetryLimit(5)
	if err != nil {
		return nil, err
	}

	return &nativeClient{db: db, joshuaNamespace: joshuaNamespace}, nil
}

func (c *nativeClient) CountPendingEnsembles(ctx context.Context) (int, error) {
	if err := ctx.Err(); err != nil {
		return 0, err
	}
	start := time.Now()
	defer func() { fdbQueryDuration.Observe(time.Since(start).Seconds()) }()

	result, err := c.db.ReadTransact(func(tr fdb.ReadTransaction) (interface{}, error) {
		return c.countPending(tr)
	})
	if err != nil {
		return 0, fmt.Errorf("FDB read transaction: %w", err)
	}

	return result.(int), nil
}

func (c *nativeClient) countPending(tr fdb.ReadTransaction) (int, error) {
	dirActive, err := directory.Open(tr, []string{c.joshuaNamespace, "ensembles", "active"}, nil)
	if err != nil {
		// Directory not yet created — no active ensembles.
		return 0, nil
	}
	dirAll, err := directory.Open(tr, []string{c.joshuaNamespace, "ensembles", "all"}, nil)
	if err != nil {
		return 0, nil
	}

	// DirectorySubspace implements fdb.Range directly via subspace.Subspace embedding.
	activeKVs, err := tr.GetRange(dirActive, fdb.RangeOptions{Mode: fdb.StreamingModeWantAll}).GetSliceWithError()
	if err != nil {
		return 0, fmt.Errorf("listing active ensembles: %w", err)
	}

	// Issue all per-ensemble range reads before resolving any, so the FDB
	// client can pipeline them over the network.
	type ensembleRead struct {
		sub subspace.Subspace
		fut fdb.RangeResult
	}
	reads := make([]ensembleRead, 0, len(activeKVs))
	for _, kv := range activeKVs {
		t, err := dirActive.Unpack(kv.Key)
		if err != nil || len(t) == 0 {
			continue
		}
		id, ok := t[0].(string)
		if !ok {
			continue
		}
		sub := dirAll.Sub(id)
		reads = append(reads, ensembleRead{
			sub: sub,
			fut: tr.GetRange(sub, fdb.RangeOptions{Mode: fdb.StreamingModeWantAll}),
		})
	}

	total := 0
	for _, rd := range reads {
		kvs, err := rd.fut.GetSliceWithError()
		if err != nil {
			continue
		}
		total += extractPending(rd.sub, kvs)
	}
	return total, nil
}

// extractPending returns max(0, max_runs - ended) for one ensemble's key-value pairs.
func extractPending(sub subspace.Subspace, kvs []fdb.KeyValue) int {
	var maxRuns, ended int64
	for _, kv := range kvs {
		t, err := sub.Unpack(kv.Key)
		if err != nil || len(t) < 2 {
			continue
		}
		category, _ := t[0].(string)
		name, _ := t[1].(string)
		switch {
		case category == "properties" && name == "max_runs":
			if vals, err := tuple.Unpack(kv.Value); err == nil && len(vals) > 0 {
				if v, ok := vals[0].(int64); ok {
					maxRuns = v
				}
			}
		case category == "count" && name == "ended":
			if len(kv.Value) == 8 {
				ended = int64(binary.LittleEndian.Uint64(kv.Value))
			}
		}
	}
	if p := maxRuns - ended; p > 0 {
		return int(p)
	}

	return 0
}
