package work

import (
	"context"
	"errors"
	"testing"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/testutil"
)

// Unit tests for your business logic. Add a row per rule you add to Process.
func TestProcess(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name       string
		item       Item
		wantStatus string
		wantErr    error
	}{
		{name: "valid item", item: Item{ID: "42"}, wantStatus: "processed"},
		{name: "missing id is rejected", item: Item{}, wantErr: ErrRejected},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			got, err := Process(context.Background(), tc.item)
			if !errors.Is(err, tc.wantErr) {
				t.Fatalf("err = %v, want %v", err, tc.wantErr)
			}
			if got.Status != tc.wantStatus {
				t.Fatalf("status = %q, want %q", got.Status, tc.wantStatus)
			}
		})
	}
}

func TestRecorderOutcomes(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		err     error
		outcome string
	}{
		{name: "success", err: nil, outcome: "success"},
		{name: "rejected", err: ErrRejected, outcome: "rejected"},
		{name: "failure", err: errors.New("boom"), outcome: "failure"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			r := NewRecorder(prometheus.NewRegistry())
			_ = r.Do(func() error { return tc.err })
			if got := testutil.ToFloat64(r.items.WithLabelValues(tc.outcome)); got != 1 {
				t.Fatalf("%s count = %v, want 1", tc.outcome, got)
			}
		})
	}
}
