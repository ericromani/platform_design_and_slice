// Command server runs __SERVICE_NAME__.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"

	"__GO_MODULE__/internal/server"
	"__GO_MODULE__/internal/work"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, logger, ":8080"); err != nil {
		logger.Error("server exited", "error", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, logger *slog.Logger, addr string) error {
	reg := prometheus.NewRegistry()
	reg.MustRegister(collectors.NewGoCollector(), collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}))

	// TODO: check what your service needs (AWS coordinates arrive as env vars, e.g.
	// SQS_<NAME>_QUEUE_NAME) and return false until it is reachable.
	ready := func(*http.Request) bool { return true }

	srv := &http.Server{
		Addr:              addr,
		Handler:           server.New(reg, work.NewRecorder(reg), ready),
		ReadHeaderTimeout: 5 * time.Second,
		BaseContext:       func(net.Listener) context.Context { return ctx },
	}
	errCh := make(chan error, 1)
	go func() {
		logger.Info("listening", "addr", addr, "service", os.Getenv("PLATFORM_SERVICE"), "version", os.Getenv("PLATFORM_VERSION"))
		errCh <- srv.ListenAndServe()
	}()

	select {
	case err := <-errCh:
		return fmt.Errorf("listen on %s: %w", addr, err)
	case <-ctx.Done():
	}
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("shutdown: %w", err)
	}
	if err := <-errCh; !errors.Is(err, http.ErrServerClosed) {
		return fmt.Errorf("listen on %s: %w", addr, err)
	}
	return nil
}
