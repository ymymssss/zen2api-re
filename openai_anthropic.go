package main

import (
	"encoding/json"
	"strings"
)

// OpenAIAnthropicAdapter converts OpenAI Chat Completions requests to Anthropic Messages.
type OpenAIAnthropicAdapter struct {
	APIKey      string
	UpstreamURL string
	cfg         *Config
}

func (a *OpenAIAnthropicAdapter) AdaptRequest(body map[string]any, _ map[string]string) *AdaptedRequest {
	messages := buildAnthropicMessages(body)
	system := extractAnthropicSystem(body)

	anthropic := map[string]any{
		"model":     body["model"],
		"messages":  messages,
		"max_tokens": getMaxTokens(body, a.cfg),
		"stream":    body["stream"],
	}

	if len(system) > 0 {
		anthropic["system"] = system
	}
	if v, ok := body["temperature"]; ok && v != nil {
		anthropic["temperature"] = v
	}
	if v, ok := body["top_p"]; ok && v != nil {
		anthropic["top_p"] = v
	}
	if v, ok := body["stop"]; ok && v != nil {
		switch s := v.(type) {
		case []any:
			anthropic["stop_sequences"] = s
		case string:
			anthropic["stop_sequences"] = []string{s}
		}
	}
	if v, ok := body["tools"]; ok && v != nil {
		anthropic["tools"] = convertOpenAITools(v)
	}
	if v, ok := body["tool_choice"]; ok && v != nil {
		anthropic["tool_choice"] = v
	}
	if v, ok := body["metadata"]; ok && v != nil {
		anthropic["metadata"] = v
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

func (a *OpenAIAnthropicAdapter) AdaptResponse(body map[string]any, statusCode int) *AdaptedResponse {
	return ConvertAnthropicToOpenAI(body, statusCode)
}

func buildAnthropicMessages(body map[string]any) []map[string]any {
	raw, _ := body["messages"].([]any)
	var out []map[string]any
	for _, r := range raw {
		msg, _ := r.(map[string]any)
		role, _ := msg["role"].(string)
		content := msg["content"]

		if role == "system" {
			continue // handled separately
		}

		am := map[string]any{"role": role}
		switch c := content.(type) {
		case string:
			am["content"] = c
		case []any:
			var parts []map[string]any
			for _, p := range c {
				part, _ := p.(map[string]any)
				ptype, _ := part["type"].(string)
				switch ptype {
				case "text":
					parts = append(parts, map[string]any{"type": "text", "text": part["text"]})
				case "image_url":
					if iu, ok := part["image_url"].(map[string]any); ok {
						if url, ok := iu["url"].(string); ok && strings.HasPrefix(url, "data:") {
							parts = append(parts, parseDataURL(url))
						}
					}
				case "tool_use", "tool_result":
					parts = append(parts, part)
				}
			}
			am["content"] = parts
		default:
			am["content"] = ""
		}
		out = append(out, am)
	}
	return out
}

func extractAnthropicSystem(body map[string]any) []map[string]any {
	// Check top-level system
	if sys, ok := body["system"]; ok {
		switch s := sys.(type) {
		case string:
			return []map[string]any{{"type": "text", "text": s}}
		case []any:
			return convertToStringParts(s)
		}
	}
	// Check messages for system role
	if msgs, ok := body["messages"].([]any); ok {
		var parts []string
		for _, m := range msgs {
			if msg, ok := m.(map[string]any); ok {
				if role, _ := msg["role"].(string); role == "system" {
					if txt, ok := msg["content"].(string); ok {
						parts = append(parts, txt)
					}
				}
			}
		}
		if len(parts) > 0 {
			return []map[string]any{{"type": "text", "text": strings.Join(parts, "\n")}}
		}
	}
	return nil
}

func getMaxTokens(body map[string]any, cfg *Config) int {
	if v, ok := body["max_tokens"].(float64); ok && v > 0 {
		return int(v)
	}
	if v, ok := body["max_output_tokens"].(float64); ok && v > 0 {
		return int(v)
	}
	return cfg.DefaultMaxTokens
}

func convertOpenAITools(v any) []map[string]any {
	tools, _ := v.([]any)
	var out []map[string]any
	for _, t := range tools {
		tool, _ := t.(map[string]any)
		fn, _ := tool["function"].(map[string]any)
		if fn == nil {
			fn = tool
		}
		out = append(out, map[string]any{
			"name":         fn["name"],
			"description":  fn["description"],
			"input_schema": fn["parameters"],
		})
	}
	return out
}

func parseDataURL(url string) map[string]any {
	parts := strings.SplitN(url, ",", 2)
	if len(parts) != 2 {
		return nil
	}
	mediaPart := strings.TrimPrefix(parts[0], "data:")
	mediaPart = strings.TrimSuffix(mediaPart, ";base64")
	return map[string]any{
		"type": "image",
		"source": map[string]any{
			"type":       "base64",
			"media_type": mediaPart,
			"data":       parts[1],
		},
	}
}

func convertToStringParts(arr []any) []map[string]any {
	var out []map[string]any
	for _, item := range arr {
		if m, ok := item.(map[string]any); ok {
			out = append(out, m)
		}
	}
	return out
}

// ── Anthropic → OpenAI (response) ──────────────────────────────────

func ConvertAnthropicToOpenAI(body map[string]any, statusCode int) *AdaptedResponse {
	openai := map[string]any{
		"id":      body["id"],
		"object":  "chat.completion",
		"created": body["created"],
		"model":   body["model"],
		"choices": []any{},
	}

	if usage, ok := body["usage"].(map[string]any); ok {
		in, _ := usage["input_tokens"].(float64)
		outT, _ := usage["output_tokens"].(float64)
		openai["usage"] = map[string]any{
			"prompt_tokens":     int(in),
			"completion_tokens": int(outT),
			"total_tokens":      int(in) + int(outT),
		}
	}

	content, _ := body["content"].([]any)
	textParts := []string{}
	var toolCalls []map[string]any

	for _, block := range content {
		b, _ := block.(map[string]any)
		switch b["type"] {
		case "text":
			if t, ok := b["text"].(string); ok {
				textParts = append(textParts, t)
			}
		case "tool_use":
			toolCalls = append(toolCalls, map[string]any{
				"id":   b["id"],
				"type": "function",
				"function": map[string]any{
					"name":      b["name"],
					"arguments": toJSONString(b["input"]),
				},
			})
		}
	}

	msg := map[string]any{"role": "assistant"}
	if len(textParts) > 0 {
		msg["content"] = strings.Join(textParts, "\n")
	}
	if len(toolCalls) > 0 {
		msg["tool_calls"] = toolCalls
	}

	openai["choices"] = []any{map[string]any{
		"index":         0,
		"message":       msg,
		"finish_reason": mapStopReason(body["stop_reason"]),
	}}

	return &AdaptedResponse{
		StatusCode: statusCode,
		Headers:    map[string]string{"content-type": "application/json"},
		Body:       openai,
	}
}

func mapStopReason(r any) string {
	s, _ := r.(string)
	switch s {
	case "end_turn":
		return "stop"
	case "max_tokens":
		return "length"
	case "tool_use":
		return "tool_calls"
	default:
		return "stop"
	}
}

func toJSONString(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}
