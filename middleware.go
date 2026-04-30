package main

import (
	"crypto/rand"
	"encoding/hex"
	"net/http"
	"strings"
	"time"
)

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "*")
		w.Header().Set("Access-Control-Allow-Headers", "*")
		if r.Method == "OPTIONS" {
			w.WriteHeader(204)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func authMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if cfg.APIKey != "" {
			clientKey := r.Header.Get("x-api-key")
			if clientKey == "" {
				auth := r.Header.Get("authorization")
				clientKey = strings.TrimPrefix(auth, "Bearer ")
			}
			if clientKey != cfg.APIKey {
				writeJSON(w, 401, map[string]any{"error": "unauthorized"})
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		wr := &responseWriter{ResponseWriter: w, status: 200}
		next.ServeHTTP(wr, r)

		path := r.URL.Path
		if path == "/health" && !cfg.LogHealthCheck {
			return
		}

		Info.Printf("%s %s -> %d (%.1fms)",
			r.Method, path, wr.status,
			float64(time.Since(start).Microseconds())/1000)
	})
}

func requestIDMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		reqID := r.Header.Get("x-request-id")
		if reqID == "" {
			b := make([]byte, 4)
			rand.Read(b)
			reqID = hex.EncodeToString(b)
		}
		w.Header().Set("x-request-id", reqID)
		next.ServeHTTP(w, r)
	})
}

type responseWriter struct {
	http.ResponseWriter
	status int
}

func (rw *responseWriter) WriteHeader(code int) {
	rw.status = code
	rw.ResponseWriter.WriteHeader(code)
}

// Flush implements http.Flusher by delegating to the underlying writer.
// This is required because Go only promotes methods from the embedded
// interface type itself, not from other interfaces the concrete value
// may satisfy. Without this, SSE streaming breaks.
func (rw *responseWriter) Flush() {
	if flusher, ok := rw.ResponseWriter.(http.Flusher); ok {
		flusher.Flush()
	}
}

// Unwrap returns the underlying ResponseWriter for type assertions.
func (rw *responseWriter) Unwrap() http.ResponseWriter {
	return rw.ResponseWriter
}
