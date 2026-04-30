package main

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"
)

var cfg *Config

func newMux() http.Handler {
	mux := http.NewServeMux()

	// Health
	mux.HandleFunc("/health", handleHealth)

	// AI API endpoints
	mux.HandleFunc("/v1/chat/completions", handleChatCompletions)
	mux.HandleFunc("/v1/messages", handleMessages)
	mux.HandleFunc("/v1/responses", handleResponses)
	mux.HandleFunc("/v1/models", handleModels)
	mux.HandleFunc("/v1/stats", handleStats)
	mux.HandleFunc("/v1/stats/flush", handleStatsFlush)

	// Admin API
	mux.HandleFunc("/admin/api/stats", handleAdminStats)
	mux.HandleFunc("/admin/api/config", handleAdminConfig)
	mux.HandleFunc("/admin/api/rate-limits", handleAdminRateLimits)
	mux.HandleFunc("/admin/api/models", handleAdminModels)
	mux.HandleFunc("/admin/api/models/refresh", handleAdminModelsRefresh)
	mux.HandleFunc("/admin/api/system", handleAdminSystem)
	mux.HandleFunc("/admin/api/captures", handleAdminCaptures)
	mux.HandleFunc("/admin/api/captures/", handleAdminCaptureDetail)

	// Admin SPA
	mux.HandleFunc("/admin", handleAdminUI)
	mux.HandleFunc("/admin/", handleAdminUI)

	// Root
	mux.HandleFunc("/", handleRoot)

	return withMiddleware(mux)
}

func withMiddleware(next http.Handler) http.Handler {
	var h http.Handler = next
	h = requestIDMiddleware(h)
	h = loggingMiddleware(h)
	h = authMiddleware(h)
	h = corsMiddleware(h)
	return h
}

// ── Health ────────────────────────────────────────────────────────

func handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]any{"status": "ok", "service": "zen2api"})
}

// ── Chat Completions ───────────────────────────────────────────────

func handleChatCompletions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "method not allowed"})
		return
	}

	body := readJSON(r)
	stream, _ := body["stream"].(bool)

	clientKey := extractKey(r)
	if !GlobalRateLimiter.TryAcquire(clientKey) {
		writeJSON(w, 429, map[string]any{"error": map[string]any{
			"message": "Rate limit exceeded",
			"type":    "rate_limit_error",
		}})
		return
	}

	adapter := &OpenAIAnthropicAdapter{
		APIKey:      cfg.APIKey,
		UpstreamURL: cfg.ZenUpstreamURL,
		cfg:         cfg,
	}

	if stream {
		adapter.streamState = newOpenAIStreamState()
		if err := proxyStreamRequest(adapter, body, headersToMap(r), "", w); err != nil {
			Error.Printf("stream failed: %v", err)
			writeJSON(w, 500, map[string]any{"error": map[string]any{"message": err.Error()}})
		}
		return
	}

	resp, err := proxyRequest(adapter, body, headersToMap(r), "")
	if err != nil {
		Error.Printf("chat completion failed: %v", err)
		writeJSON(w, 500, map[string]any{"error": map[string]any{"message": err.Error()}})
		return
	}
	writeJSON(w, resp.StatusCode, resp.Body)
}

// ── Messages (Anthropic) ───────────────────────────────────────────

func handleMessages(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "method not allowed"})
		return
	}

	body := readJSON(r)
	stream, _ := body["stream"].(bool)
	clientKey := extractKey(r)

	if !GlobalRateLimiter.TryAcquire(clientKey) {
		writeJSON(w, 429, map[string]any{"type": "error", "error": map[string]any{
			"type":    "rate_limit_error",
			"message": "Rate limit exceeded",
		}})
		return
	}

	model := extractModelFromBody(body)
	useKilo := isKiloModel(model)

	var adapter Adapter
	if useKilo {
		adapter = &AnthropicOpenAIAdapter{
			APIKey:      cfg.APIKey,
			UpstreamURL: cfg.KiloUpstreamURL,
			cfg:         cfg,
		}
	} else {
		adapter = &AnthropicPassthroughAdapter{
			APIKey:      cfg.APIKey,
			UpstreamURL: cfg.ZenUpstreamURL,
			cfg:         cfg,
		}
	}

	if stream {
		// Initialize stream state for adapters that support it
		if a, ok := adapter.(*AnthropicOpenAIAdapter); ok {
			a.streamState = newAnthropicStreamState()
		}
		if err := proxyStreamRequest(adapter, body, headersToMap(r), "", w); err != nil {
			writeJSON(w, 500, map[string]any{"type": "error", "error": map[string]any{"message": err.Error()}})
		}
		return
	}

	resp, err := proxyRequest(adapter, body, headersToMap(r), "")
	if err != nil {
		writeJSON(w, 500, map[string]any{"type": "error", "error": map[string]any{"message": err.Error()}})
		return
	}
	writeJSON(w, resp.StatusCode, resp.Body)
}

// ── Responses ──────────────────────────────────────────────────────

func handleResponses(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "method not allowed"})
		return
	}

	body := readJSON(r)
	clientKey := extractKey(r)

	if !GlobalRateLimiter.TryAcquire(clientKey) {
		writeJSON(w, 429, map[string]any{"error": map[string]any{"message": "Rate limit exceeded"}})
		return
	}

	adapter := &ResponsesAdapter{
		APIKey:      cfg.APIKey,
		UpstreamURL: cfg.ZenUpstreamURL,
		cfg:         cfg,
	}

	resp, err := proxyRequest(adapter, body, headersToMap(r), "")
	if err != nil {
		writeJSON(w, 500, map[string]any{"error": map[string]any{"message": err.Error()}})
		return
	}
	writeJSON(w, resp.StatusCode, resp.Body)
}

// ── Models ─────────────────────────────────────────────────────────

func handleModels(w http.ResponseWriter, r *http.Request) {
	zen, kilo := DiscoverModels(cfg)
	all := make([]any, 0, len(zen)+len(kilo))
	seen := map[string]bool{}
	for _, m := range zen {
		id, _ := m["id"].(string)
		if !seen[id] {
			seen[id] = true
			all = append(all, m)
		}
	}
	for _, m := range kilo {
		id, _ := m["id"].(string)
		if !seen[id] {
			seen[id] = true
			all = append(all, m)
		}
	}
	writeJSON(w, 200, map[string]any{"object": "list", "data": all})
}

// ── Stats ──────────────────────────────────────────────────────────

func handleStats(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]any{"usage": UsageSnapshot()})
}

func handleStatsFlush(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "method not allowed"})
		return
	}
	WriteStatsFile(cfg.StatsFile)
	writeJSON(w, 200, map[string]any{"status": "ok"})
}

// ── Root ───────────────────────────────────────────────────────────

func handleRoot(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		writeJSON(w, 404, map[string]any{"error": "not found"})
		return
	}
	writeJSON(w, 200, map[string]any{"service": "zen2api", "version": "1.0.0"})
}

// ── Helpers ────────────────────────────────────────────────────────

func readJSON(r *http.Request) map[string]any {
	var body map[string]any
	data, _ := io.ReadAll(r.Body)
	json.Unmarshal(data, &body)
	if body == nil {
		body = map[string]any{}
	}
	return body
}

func writeJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(data)
}

func headersToMap(r *http.Request) map[string]string {
	h := make(map[string]string)
	for k, v := range r.Header {
		h[k] = strings.Join(v, ", ")
	}
	return h
}

func extractKey(r *http.Request) string {
	key := r.Header.Get("x-api-key")
	if key == "" {
		key = r.Header.Get("authorization")
		key = strings.TrimPrefix(key, "Bearer ")
	}
	if key == "" {
		key = "default"
	}
	return key
}

// ── Passthrough adapter (Anthropic native) ─────────────────────────

type AnthropicPassthroughAdapter struct {
	APIKey      string
	UpstreamURL string
	cfg         *Config
}

func (a *AnthropicPassthroughAdapter) AdaptRequest(body map[string]any, _ map[string]string) *AdaptedRequest {
	return &AdaptedRequest{
		URL:    a.UpstreamURL,
		Method: "POST",
		Headers: map[string]string{
			"content-type":      "application/json",
			"x-api-key":         a.APIKey,
			"anthropic-version": a.cfg.ZenAnthropicVersion,
		},
		Body: body,
	}
}

func (a *AnthropicPassthroughAdapter) AdaptResponse(body map[string]any, status int) *AdaptedResponse {
	return &AdaptedResponse{
		StatusCode: status,
		Headers:    map[string]string{"content-type": "application/json"},
		Body:       body,
	}
}

// ── Responses adapter ──────────────────────────────────────────────

type ResponsesAdapter struct {
	APIKey      string
	UpstreamURL string
	cfg         *Config
}

func (a *ResponsesAdapter) AdaptRequest(body map[string]any, _ map[string]string) *AdaptedRequest {
	input := body["input"]
	messages := input

	switch v := input.(type) {
	case string:
		messages = []map[string]any{{"role": "user", "content": v}}
	case []any:
		messages = v
	}

	anthropic := map[string]any{
		"model":     body["model"],
		"messages":  messages,
		"max_tokens": getMaxTokens(body, a.cfg),
		"stream":    body["stream"],
	}

	if instructions, ok := body["instructions"].(string); ok && instructions != "" {
		anthropic["system"] = []map[string]any{{"type": "text", "text": instructions}}
	}
	if v, ok := body["temperature"]; ok {
		anthropic["temperature"] = v
	}
	if v, ok := body["tools"]; ok {
		anthropic["tools"] = v
	}

	return &AdaptedRequest{
		URL:    a.UpstreamURL,
		Method: "POST",
		Headers: map[string]string{
			"content-type":      "application/json",
			"x-api-key":         a.APIKey,
			"anthropic-version": a.cfg.ZenAnthropicVersion,
		},
		Body: anthropic,
	}
}

func (a *ResponsesAdapter) AdaptResponse(body map[string]any, status int) *AdaptedResponse {
	content, _ := body["content"].([]any)
	var output []map[string]any
	for _, block := range content {
		b, _ := block.(map[string]any)
		switch b["type"] {
		case "text":
			output = append(output, map[string]any{"type": "output_text", "text": b["text"]})
		case "tool_use":
			output = append(output, map[string]any{
				"type":      "function_call",
				"id":        b["id"],
				"name":      b["name"],
				"arguments": b["input"],
			})
		}
	}

	usage, _ := body["usage"].(map[string]any)
	in, _ := usage["input_tokens"].(float64)
	out, _ := usage["output_tokens"].(float64)

	return &AdaptedResponse{
		StatusCode: status,
		Headers:    map[string]string{"content-type": "application/json"},
		Body: map[string]any{
			"id":      body["id"],
			"object":  "response",
			"model":   body["model"],
			"output":  output,
			"usage": map[string]any{
				"input_tokens":  int(in),
				"output_tokens": int(out),
				"total_tokens":  int(in) + int(out),
			},
		},
	}
}

// isKiloModel checks whether a model ID should be routed to the Kilo upstream.
// Uses cached data only; does not trigger model discovery.
func isKiloModel(model string) bool {
	modelLock.RLock()
	kiloModels := modelCache["kilo"]
	modelLock.RUnlock()

	for _, m := range kiloModels {
		if id, ok := m["id"].(string); ok && strings.EqualFold(id, model) {
			return true
		}
	}
	return false
}
