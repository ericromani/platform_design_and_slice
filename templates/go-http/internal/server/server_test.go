package server

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/prometheus/client_golang/prometheus"

	"__GO_MODULE__/internal/work"
)

// Platform contract tests: probes and metrics must keep working. Keep these.
func newServer(t *testing.T, ready bool) *httptest.Server {
	t.Helper()
	reg := prometheus.NewRegistry()
	srv := httptest.NewServer(New(reg, work.NewRecorder(reg), func(*http.Request) bool { return ready }))
	t.Cleanup(srv.Close)
	return srv
}

func TestProbes(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name  string
		ready bool
		path  string
		want  int
	}{
		{name: "liveness ignores dependencies", ready: false, path: "/healthz", want: http.StatusOK},
		{name: "ready", ready: true, path: "/readyz", want: http.StatusOK},
		{name: "not ready", ready: false, path: "/readyz", want: http.StatusServiceUnavailable},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			resp, err := http.Get(newServer(t, tc.ready).URL + tc.path)
			if err != nil {
				t.Fatal(err)
			}
			defer resp.Body.Close()
			if resp.StatusCode != tc.want {
				t.Fatalf("GET %s = %d, want %d", tc.path, resp.StatusCode, tc.want)
			}
		})
	}
}

func TestMetricsContract(t *testing.T) {
	t.Parallel()
	srv := newServer(t, true)
	post, err := http.Post(srv.URL+"/work", "application/json", strings.NewReader(`{"id":"1"}`))
	if err != nil {
		t.Fatal(err)
	}
	post.Body.Close()
	resp, err := http.Get(srv.URL + "/metrics")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	for _, want := range []string{`http_requests_total{method="POST",path="/work",status="200"} 1`, `app_work_items_total{outcome="success"} 1`} {
		if !strings.Contains(string(body), want) {
			t.Errorf("metrics missing %q", want)
		}
	}
}
