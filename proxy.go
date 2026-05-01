package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"
)

// customDialer 在 Android/Termux 环境下使用 8.8.8.8 做 DNS 解析，
// 因为 Android 的 [::1]:53 DNS 代理可能没有运行。
var customDialer = &net.Dialer{
	Timeout:   30 * time.Second,
	KeepAlive: 30 * time.Second,
	Resolver: &net.Resolver{
		PreferGo: true,
		Dial: func(ctx context.Context, network, address string) (net.Conn, error) {
			d := net.Dialer{Timeout: 10 * time.Second}
			return d.DialContext(ctx, "udp", "8.8.8.8:53")
		},
	},
}

var proxyClient = &http.Client{
	Timeout: 600 * time.Second,
	Transport: &http.Transport{
		DialContext:           customDialer.DialContext,
		MaxIdleConns:          100,
		MaxIdleConnsPerHost:   20,
		IdleConnTimeout:       30 * time.Second,
		ResponseHeaderTimeout: 30 * time.Second,
	},
}

func proxyRequest(adapter Adapter, reqBody map[string]any, reqHeaders map[string]string, upstreamURL string) (*AdaptedResponse, error) {
	adapted := adapter.AdaptRequest(reqBody, reqHeaders)
	if upstreamURL != "" {
		adapted.URL = upstreamURL
	}
	if adapted.URL == "" {
		return nil, fmt.Errorf("no upstream URL configured")
	}

	bodyBytes, _ := json.Marshal(adapted.Body)
	req, err := http.NewRequest(adapted.Method, adapted.URL, bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, err
	}
	for k, v := range adapted.Headers {
		req.Header.Set(k, v)
	}

	resp, err := proxyClient.Do(req)
	if err != nil {
		StatsRecordError()
		return nil, err
	}
	defer resp.Body.Close()

	respBytes, _ := io.ReadAll(resp.Body)
	var respBody map[string]any
	json.Unmarshal(respBytes, &respBody)

	if respBody == nil {
		respBody = map[string]any{"text": string(respBytes)}
	}

	StatsRecordRequest()
	RecordTokenUsage(respBody)

	return adapter.AdaptResponse(respBody, resp.StatusCode), nil
}

func proxyStreamRequest(adapter Adapter, reqBody map[string]any, reqHeaders map[string]string, upstreamURL string, w http.ResponseWriter) error {
	adapted := adapter.AdaptRequest(reqBody, reqHeaders)
	if upstreamURL != "" {
		adapted.URL = upstreamURL
	}

	bodyBytes, _ := json.Marshal(adapted.Body)
	req, err := http.NewRequest(adapted.Method, adapted.URL, bytes.NewReader(bodyBytes))
	if err != nil {
		return err
	}
	for k, v := range adapted.Headers {
		req.Header.Set(k, v)
	}

	resp, err := proxyClient.Do(req)
	if err != nil {
		StatsRecordError()
		return err
	}
	defer resp.Body.Close()

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	flusher, ok := w.(http.Flusher)
	if !ok {
		return fmt.Errorf("streaming not supported")
	}

	// Check if adapter supports streaming transformation
	streamAdapter, hasStreamAdapter := adapter.(StreamAdapter)

	if hasStreamAdapter {
		// Use line-by-line reading with SSE transformation
		scanner := bufio.NewScanner(resp.Body)
		// Increase buffer for large SSE events (e.g., large tool definitions)
		scanner.Buffer(make([]byte, 64*1024), 1024*1024)

		for scanner.Scan() {
			line := scanner.Text()

			transformed := streamAdapter.TransformSSEEvent(line)
			for _, t := range transformed {
				if _, err := w.Write([]byte(t)); err != nil {
					return err
				}
			}
			flusher.Flush()
		}

		// Write final SSE events (e.g., [DONE])
		for _, final := range streamAdapter.FinalizeSSE() {
			if _, err := w.Write([]byte(final)); err != nil {
				return err
			}
		}
		flusher.Flush()

		if err := scanner.Err(); err != nil {
			Warning.Printf("SSE scanner error: %v", err)
		}
	} else {
		// Passthrough mode: read line-by-line without transformation
		scanner := bufio.NewScanner(resp.Body)
		scanner.Buffer(make([]byte, 64*1024), 1024*1024)

		for scanner.Scan() {
			line := scanner.Text() + "\n"
			if _, err := w.Write([]byte(line)); err != nil {
				return err
			}
			flusher.Flush()
		}

		if err := scanner.Err(); err != nil {
			Warning.Printf("SSE passthrough scanner error: %v", err)
		}
	}

	StatsRecordRequest()
	return nil
}

// extractModelFromBody tries to get the model name from a request body.
func extractModelFromBody(body map[string]any) string {
	if m, ok := body["model"].(string); ok {
		return normalizeModelName(strings.TrimSpace(m))
	}
	return "unknown"
}

// normalizeModelName repairs model names that have had their dots turned into hyphens
// by normalizers that assume Anthropic-style naming (e.g. minimax-m2-5-free → minimax-m2.5-free).
// Only applies the repair when the model name does NOT already contain a dot,
// otherwise a correctly-dotted name like minimax-m2.5-free would be broken into
// minimax-m2.5.free by replacing the hyphen before "free".
func normalizeModelName(model string) string {
	if strings.HasPrefix(model, "minimax-") && !strings.Contains(model, ".") {
		rest := strings.TrimPrefix(model, "minimax-")
		if idx := strings.Index(rest, "-"); idx > 0 {
			model = "minimax-" + rest[:idx] + "." + rest[idx+1:]
		}
	}
	return model
}
