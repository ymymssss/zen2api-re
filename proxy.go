package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

var proxyClient = &http.Client{
	Timeout: 600 * time.Second,
	Transport: &http.Transport{
		MaxIdleConns:        100,
		MaxIdleConnsPerHost: 20,
		IdleConnTimeout:     30 * time.Second,
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
		return strings.TrimSpace(m)
	}
	return "unknown"
}
