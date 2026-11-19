//go:build integration

// Integration tests against LocalStack. The central build runs them with a LocalStack
// service container (go test -tags integration ./...). Locally:
//
//	LOCALSTACK_ENDPOINT=http://localhost:4566 go test -tags integration ./...
package integration

import (
	"net/http"
	"os"
	"testing"
)

func TestLocalStackReachable(t *testing.T) {
	endpoint := os.Getenv("LOCALSTACK_ENDPOINT")
	if endpoint == "" {
		t.Skip("LOCALSTACK_ENDPOINT not set")
	}
	// TODO: replace with your service's real flow using aws-sdk-go-v2 with
	// BaseEndpoint set to LOCALSTACK_ENDPOINT (e.g. send to your queue, assert the row).
	resp, err := http.Get(endpoint + "/_localstack/health")
	if err != nil {
		t.Fatalf("LocalStack unreachable: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("health = %d", resp.StatusCode)
	}
}
