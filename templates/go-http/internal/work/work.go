// Package work holds the service's unit of work. Replace Process with your logic.
//
// Every item must be reported through Recorder so the platform's rollout analysis can
// judge new releases: a canary whose failure ratio exceeds
// rollout.analysis.maxWorkFailureRatio is rolled back automatically.
package work

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/prometheus/client_golang/prometheus"
)

// ErrRejected marks bad input that retrying will never fix (outcome="rejected").
var ErrRejected = errors.New("rejected")

// Item is one unit of work.
type Item struct {
	ID string `json:"id"`
}

// Result is what processing an Item produces.
type Result struct {
	ID     string `json:"id"`
	Status string `json:"status"`
}

// Process handles one item.
// TODO: implement your business logic. Wrap ErrRejected for invalid input; any other
// error counts as a failure.
func Process(ctx context.Context, item Item) (Result, error) {
	if err := ctx.Err(); err != nil {
		return Result{}, fmt.Errorf("process %q: %w", item.ID, err)
	}
	if item.ID == "" {
		return Result{}, fmt.Errorf("item needs an id: %w", ErrRejected)
	}
	return Result{ID: item.ID, Status: "processed"}, nil
}

// Recorder counts work outcomes using the platform metric contract:
// app_work_items_total{outcome} and app_work_duration_seconds.
type Recorder struct {
	items    *prometheus.CounterVec
	duration prometheus.Histogram
}

// NewRecorder registers the work metrics on reg.
func NewRecorder(reg prometheus.Registerer) *Recorder {
	r := &Recorder{
		items: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "app_work_items_total",
			Help: "Background work items processed.",
		}, []string{"outcome"}),
		duration: prometheus.NewHistogram(prometheus.HistogramOpts{
			Name:    "app_work_duration_seconds",
			Help:    "Time to process one work item.",
			Buckets: []float64{0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5},
		}),
	}
	reg.MustRegister(r.items, r.duration)
	for _, o := range []string{"success", "failure", "rejected"} {
		r.items.WithLabelValues(o)
	}
	return r
}

// Do runs fn and records its outcome and duration.
func (r *Recorder) Do(fn func() error) error {
	start := time.Now()
	err := fn()
	outcome := "success"
	switch {
	case errors.Is(err, ErrRejected):
		outcome = "rejected"
	case err != nil:
		outcome = "failure"
	}
	r.items.WithLabelValues(outcome).Inc()
	r.duration.Observe(time.Since(start).Seconds())
	return err
}
