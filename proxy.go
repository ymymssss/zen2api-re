package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
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

	// Pass through SSE chunks — for Anthropic → OpenAI streaming, we'd transform
	// For now, pass through and let the client handle it
	buf := make([]byte, 4096)
	for {
		n, err := resp.Body.Read(buf)
		if n > 0 {
			// Transform SSE if needed
			transformed := transformSSEChunk(buf[:n], adapter)
			if _, werr := w.Write(transformed); werr != nil {
				return werr
			}
			flusher.Flush()
		}
		if err != nil {
			break
		}
	}

	StatsRecordRequest()
	return nil
}

func transformSSEChunk(data []byte, adapter Adapter) []byte {
	return data // default: pass-through; adapters can override by type assertion
}
