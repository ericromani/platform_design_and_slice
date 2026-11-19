// Package server is the HTTP surface required by the platform contract (do not remove):
//
//	/healthz  liveness  - the process is up; never checks dependencies
//	/readyz   readiness - dependencies reachable; 503 until they are
//	/metrics  Prometheus text format, scraped by Grafana Alloy
package server

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"__GO_MODULE__/internal/work"
)

// ReadyFunc reports whether the service's dependencies are reachable.
type ReadyFunc func(r *http.Request) bool

// New builds the handler. Dependencies are passed in, so tests need no globals.
func New(reg *prometheus.Registry, recorder *work.Recorder, ready ReadyFunc) http.Handler {
	requests := prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "http_requests_total",
		Help: "HTTP requests served.",
	}, []string{"method", "path", "status"})
	reg.MustRegister(requests)

	mux := http.NewServeMux()
	handle := func(pattern, path string, h http.HandlerFunc) {
		mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) {
			sw := &statusWriter{ResponseWriter: w, status: http.StatusOK}
			h(sw, r)
			requests.WithLabelValues(r.Method, path, strconv.Itoa(sw.status)).Inc()
		})
	}

	handle("GET /healthz", "/healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	handle("GET /readyz", "/readyz", func(w http.ResponseWriter, r *http.Request) {
		if !ready(r) {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "not ready"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
	})
	handle("POST /work", "/work", func(w http.ResponseWriter, r *http.Request) {
		var item work.Item
		if err := json.NewDecoder(r.Body).Decode(&item); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON"})
			return
		}
		var res work.Result
		err := recorder.Do(func() error {
			var err error
			res, err = work.Process(r.Context(), item)
			return err
		})
		switch {
		case errors.Is(err, work.ErrRejected):
			writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"error": err.Error()})
		case err != nil:
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "processing failed"})
		default:
			writeJSON(w, http.StatusOK, res)
		}
	})
	mux.Handle("GET /metrics", promhttp.HandlerFor(reg, promhttp.HandlerOpts{}))
	return mux
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (s *statusWriter) WriteHeader(code int) {
	s.status = code
	s.ResponseWriter.WriteHeader(code)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
