package main

import (
	"bytes"
	"context"
	_ "embed"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

//go:embed webui/index.html
var adminHTML string

func main() {
	cfg = LoadConfig()
	SetupLogging(cfg)
	InitRateLimiter(cfg)

	Info.Printf("zen2api v1.0.0 starting …")

	// Warm model cache in background
	WarmModelCache(cfg)
	StartStatsWriter(cfg)

	// Determine which services to start
	mainEnabled := cfg.ZEN2APIEnabled
	anyrouterEnabled := cfg.AnyRouterEnabled

	if !mainEnabled && !anyrouterEnabled {
		Error.Fatalf("No service enabled. Set ZEN2API_ENABLED=1 or ZEN2API_ANYROUTER_ENABLED=1")
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	errCh := make(chan error, 2)

	if mainEnabled {
		go func() {
			mux := newMux()
			addr := fmt.Sprintf("%s:%s", cfg.Host, cfg.Port)
			Info.Printf("main server listening on http://%s", addr)
			Info.Printf("admin panel: http://%s/admin", addr)
			if err := http.ListenAndServe(addr, mux); err != nil {
				errCh <- fmt.Errorf("main server: %w", err)
			}
		}()
	}

	if anyrouterEnabled {
		go func() {
			amux := newAnyRouterMux()
			addr := fmt.Sprintf("%s:%s", cfg.Host, cfg.AnyRouterPort)
			Info.Printf("anyrouter listening on http://%s (capture: %v)", addr, cfg.AnyRouterCaptureEnabled)
			if err := http.ListenAndServe(addr, amux); err != nil {
				errCh <- fmt.Errorf("anyrouter: %w", err)
			}
		}()
	}

	// Wait for shutdown signal
	select {
	case err := <-errCh:
		Error.Printf("server error: %v", err)
	case <-ctx.Done():
		Info.Printf("shutting down …")
	}

	// Graceful shutdown
	WriteStatsFile(cfg.StatsFile)
	Info.Printf("zen2api stopped")
}

// ── AnyRouter ──────────────────────────────────────────────────────

func newAnyRouterMux() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", handleAnyRouterProxy)
	return mux
}

func handleAnyRouterProxy(w http.ResponseWriter, r *http.Request) {
	upstreamURL := "https://api.anthropic.com" + r.URL.Path
	if r.URL.RawQuery != "" {
		upstreamURL += "?" + r.URL.RawQuery
	}

	reqBody, _ := io.ReadAll(r.Body)

	req, err := http.NewRequest(r.Method, upstreamURL, bytes.NewReader(reqBody))
	if err != nil {
		http.Error(w, err.Error(), 502)
		return
	}
	req.ContentLength = int64(len(reqBody))
	req.Header.Set("Content-Type", "application/json")

	// Forward select headers
	for _, key := range []string{"x-api-key", "anthropic-version", "content-type", "accept"} {
		if v := r.Header.Get(key); v != "" {
			req.Header.Set(key, v)
		}
	}

	resp, err := proxyClient.Do(req)
	if err != nil {
		Error.Printf("anyrouter upstream error: %v", err)
		http.Error(w, err.Error(), 502)
		return
	}
	defer resp.Body.Close()

	// Copy response
	for k, vv := range resp.Header {
		for _, v := range vv {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body)

	// Capture if enabled
	if cfg.AnyRouterCaptureEnabled {
		captureRequest(r, reqBody, resp.StatusCode)
	}
}

func captureRequest(r *http.Request, reqBody []byte, status int) {
	os.MkdirAll(cfg.AnyRouterCaptureDir, 0755)
	fname := fmt.Sprintf("%s/capture_%d.json", cfg.AnyRouterCaptureDir, time.Now().UnixMicro())
	// Simple capture — write key metadata
	capture := fmt.Sprintf(`{"method":"%s","path":"%s","status":%d,"timestamp":%d}`,
		r.Method, r.URL.Path, status, time.Now().UnixMicro())
	os.WriteFile(fname, []byte(capture), 0644)
}
