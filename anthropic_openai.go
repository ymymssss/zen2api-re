package main

import (
	"encoding/json"
	"fmt"
	"strings"
)

// AnthropicOpenAIAdapter converts Anthropic Messages requests to OpenAI Chat Completions.
type AnthropicOpenAIAdapter struct {
	APIKey      string
	UpstreamURL string
	cfg         *Config
	streamState *anthropicStreamState
}

func (a *AnthropicOpenAIAdapter) AdaptRequest(body map[string]any, _ map[string]string) *AdaptedRequest {
	messages := buildOpenAIMessages(body)

	openaiBody := map[string]any{
		"model":    body["model"],
		"messages": messages,
		"stream":   body["stream"],
	}

	if v, ok := body["max_tokens"].(float64); ok && v > 0 {
		openaiBody["max_tokens"] = int(v)
	} else {
		openaiBody["max_tokens"] = a.cfg.DefaultMaxTokens
	}
	if v, ok := body["temperature"]; ok && v != nil {
		openaiBody["temperature"] = v
	}
	if v, ok := body["top_p"]; ok && v != nil {
		openaiBody["top_p"] = v
	}
	if v, ok := body["stop_sequences"]; ok {
		openaiBody["stop"] = v
	}
	if v, ok := body["tools"]; ok {
		openaiBody["tools"] = convertAnthropicTools(v)
	}

	return &AdaptedRequest{
		URL:    a.UpstreamURL,
		Method: "POST",
		Headers: map[string]string{
			"content-type":  "application/json",
			"authorization": "Bearer " + a.APIKey,
		},
		Body: openaiBody,
	}
}

func (a *AnthropicOpenAIAdapter) AdaptResponse(body map[string]any, statusCode int) *AdaptedResponse {
	return ConvertOpenAIToAnthropic(body, statusCode)
}

func buildOpenAIMessages(body map[string]any) []map[string]any {
	var messages []map[string]any

	// System prompt
	if sys := extractSystemStr(body); sys != "" {
		messages = append(messages, map[string]any{"role": "system", "content": sys})
	}

	// Messages
	if msgList, ok := body["messages"].([]any); ok {
		for _, m := range msgList {
			msg, _ := m.(map[string]any)
			role, _ := msg["role"].(string)
			content := msg["content"]

			om := map[string]any{"role": role}
			switch c := content.(type) {
			case string:
				om["content"] = c
			case []any:
				var text []string
				var toolCalls []map[string]any
				var openaiParts []map[string]any

				for _, block := range c {
					b, _ := block.(map[string]any)
					switch b["type"] {
					case "text":
						if t, ok := b["text"].(string); ok {
							text = append(text, t)
							openaiParts = append(openaiParts, map[string]any{"type": "text", "text": t})
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
					case "tool_result":
						openaiParts = append(openaiParts, map[string]any{
							"type":    "text",
							"text":    toJSONString(b["content"]),
						})
					case "image":
						if src, ok := b["source"].(map[string]any); ok {
							openaiParts = append(openaiParts, map[string]any{
								"type": "image_url",
								"image_url": map[string]any{
									"url": "data:" + str(src["media_type"]) + ";base64," + str(src["data"]),
								},
							})
						}
					}
				}

				if len(openaiParts) > 0 {
					om["content"] = openaiParts
				}
				if len(toolCalls) > 0 {
					om["tool_calls"] = toolCalls
				}
				if len(text) > 0 && len(openaiParts) == 0 && len(toolCalls) == 0 {
					om["content"] = text[0]
				}
			}
			messages = append(messages, om)
		}
	}
	return messages
}

func extractSystemStr(body map[string]any) string {
	if s, ok := body["system"].(string); ok {
		return s
	}
	if arr, ok := body["system"].([]any); ok {
		var parts []string
		for _, a := range arr {
			if m, ok := a.(map[string]any); ok {
				if t, ok := m["text"].(string); ok {
					parts = append(parts, t)
				}
			}
		}
		if len(parts) > 0 {
			return join(parts, "\n")
		}
	}
	return ""
}

func join(parts []string, sep string) string {
	if len(parts) == 0 {
		return ""
	}
	s := parts[0]
	for _, p := range parts[1:] {
		s += sep + p
	}
	return s
}

func str(v any) string {
	s, _ := v.(string)
	return s
}

func convertAnthropicTools(v any) []map[string]any {
	tools, _ := v.([]any)
	var out []map[string]any
	for _, t := range tools {
		tool, _ := t.(map[string]any)
		out = append(out, map[string]any{
			"type": "function",
			"function": map[string]any{
				"name":        tool["name"],
				"description": tool["description"],
				"parameters":  tool["input_schema"],
			},
		})
	}
	return out
}

// ── OpenAI → Anthropic (response) ──────────────────────────────────

func ConvertOpenAIToAnthropic(body map[string]any, statusCode int) *AdaptedResponse {
	choices, _ := body["choices"].([]any)
	var content []map[string]any

	if len(choices) > 0 {
		choice, _ := choices[0].(map[string]any)
		msg, _ := choice["message"].(map[string]any)

		if text, ok := msg["content"].(string); ok && text != "" {
			content = append(content, map[string]any{"type": "text", "text": text})
		}

		if toolCalls, ok := msg["tool_calls"].([]any); ok {
			for _, tc := range toolCalls {
				t, _ := tc.(map[string]any)
				fn, _ := t["function"].(map[string]any)
				var args any
				if a, ok := fn["arguments"].(string); ok {
					json.Unmarshal([]byte(a), &args)
				}
				content = append(content, map[string]any{
					"type":  "tool_use",
					"id":    t["id"],
					"name":  fn["name"],
					"input": args,
				})
			}
		}
	}

	usage, _ := body["usage"].(map[string]any)
	in, _ := usage["prompt_tokens"].(float64)
	out, _ := usage["completion_tokens"].(float64)

	anthropic := map[string]any{
		"id":           body["id"],
		"type":         "message",
		"role":         "assistant",
		"model":        body["model"],
		"content":      content,
		"stop_reason":  mapStopReasonToAnthropic(choices),
		"stop_sequence": nil,
		"usage": map[string]any{
			"input_tokens":  int(in),
			"output_tokens": int(out),
		},
	}

	return &AdaptedResponse{
		StatusCode: statusCode,
		Headers:    map[string]string{"content-type": "application/json"},
		Body:       anthropic,
	}
}

func mapStopReasonToAnthropic(choices []any) string {
	if len(choices) == 0 {
		return "end_turn"
	}
	choice, _ := choices[0].(map[string]any)
	reason, _ := choice["finish_reason"].(string)
	switch reason {
	case "stop":
		return "end_turn"
	case "length":
		return "max_tokens"
	case "tool_calls":
		return "tool_use"
	default:
		return "end_turn"
	}
}

// ── StreamAdapter implementation (OpenAI SSE → Anthropic SSE) ──────

type anthropicStreamState struct {
	msgID        string
	model        string
	msgStarted   bool
	textBlockIdx int
	textStarted  bool
	nextBlockIdx int
	toolBlocks   map[int]*toolBlockState
	finishReason string
	finalUsage   map[string]any
}

type toolBlockState struct {
	anthropicIdx int
	id           string
	name         string
	started      bool
}

func newAnthropicStreamState() *anthropicStreamState {
	return &anthropicStreamState{
		msgID:      "msg_" + randomHex(24),
		toolBlocks: make(map[int]*toolBlockState),
		textBlockIdx: -1,
	}
}

func (a *AnthropicOpenAIAdapter) TransformSSEEvent(line string) []string {
	return transformOpenAISSEToAnthropic(line, a.streamState)
}

func (a *AnthropicOpenAIAdapter) FinalizeSSE() []string {
	st := a.streamState
	if st == nil || !st.msgStarted {
		return nil
	}
	var results []string

	// Emit content_block_stop for text
	if st.textBlockIdx >= 0 {
		data, _ := json.Marshal(map[string]any{
			"type":  "content_block_stop",
			"index": st.textBlockIdx,
		})
		results = append(results, fmt.Sprintf("event: content_block_stop\ndata: %s\n\n", string(data)))
	}

	// Emit content_block_stop for tool blocks
	for _, tb := range st.toolBlocks {
		if tb.started {
			data, _ := json.Marshal(map[string]any{
				"type":  "content_block_stop",
				"index": tb.anthropicIdx,
			})
			results = append(results, fmt.Sprintf("event: content_block_stop\ndata: %s\n\n", string(data)))
		}
	}

	// Emit message_delta
	finishReason := st.finishReason
	if finishReason == "" {
		finishReason = "end_turn"
	}
	msgDelta := map[string]any{
		"type": "message_delta",
		"delta": map[string]any{
			"stop_reason":   finishReason,
			"stop_sequence": nil,
		},
		"usage": map[string]any{"output_tokens": 0},
	}
	if st.finalUsage != nil {
		if ct, ok := st.finalUsage["completion_tokens"].(float64); ok {
			msgDelta["usage"] = map[string]any{"output_tokens": int(ct)}
		}
	}
	deltaData, _ := json.Marshal(msgDelta)
	results = append(results, fmt.Sprintf("event: message_delta\ndata: %s\n\n", string(deltaData)))

	// Emit message_stop
	stopData, _ := json.Marshal(map[string]any{"type": "message_stop"})
	results = append(results, fmt.Sprintf("event: message_stop\ndata: %s\n\n", string(stopData)))

	return results
}

var _ StreamAdapter = (*AnthropicOpenAIAdapter)(nil)

func transformOpenAISSEToAnthropic(line string, st *anthropicStreamState) []string {
	if st == nil {
		return nil
	}

	trimmed := strings.TrimSpace(line)
	if !strings.HasPrefix(trimmed, "data: ") {
		return nil
	}

	payload := strings.TrimPrefix(trimmed, "data: ")
	if payload == "[DONE]" {
		return nil
	}

	var obj map[string]any
	if err := json.Unmarshal([]byte(payload), &obj); err != nil {
		return nil
	}

	choices, _ := obj["choices"].([]any)
	if len(choices) == 0 {
		return nil
	}
	choice, _ := choices[0].(map[string]any)
	delta, _ := choice["delta"].(map[string]any)

	var results []string

	if m, ok := obj["model"].(string); ok && m != "" {
		st.model = m
	}

	// Emit message_start on first event
	if !st.msgStarted {
		startData, _ := json.Marshal(map[string]any{
			"type": "message_start",
			"message": map[string]any{
				"id":           st.msgID,
				"type":         "message",
				"role":         "assistant",
				"model":        st.model,
				"content":      []any{},
				"stop_reason":  nil,
				"stop_sequence": nil,
				"usage":        map[string]any{"input_tokens": 0, "output_tokens": 1},
			},
		})
		results = append(results, fmt.Sprintf("event: message_start\ndata: %s\n\n", string(startData)))
		st.msgStarted = true
	}

	// Handle text delta
	if content, ok := delta["content"].(string); ok && content != "" {
		if !st.textStarted {
			st.textBlockIdx = st.nextBlockIdx
			st.nextBlockIdx++
			cbData, _ := json.Marshal(map[string]any{
				"type":  "content_block_start",
				"index": st.textBlockIdx,
				"content_block": map[string]any{
					"type": "text",
					"text": "",
				},
			})
			results = append(results, fmt.Sprintf("event: content_block_start\ndata: %s\n\n", string(cbData)))
			st.textStarted = true
		}
		deltaData, _ := json.Marshal(map[string]any{
			"type":  "content_block_delta",
			"index": st.textBlockIdx,
			"delta": map[string]any{
				"type": "text_delta",
				"text": content,
			},
		})
		results = append(results, fmt.Sprintf("event: content_block_delta\ndata: %s\n\n", string(deltaData)))
	}

	// Handle tool calls
	if toolCalls, ok := delta["tool_calls"].([]any); ok {
		for _, tc := range toolCalls {
			tcMap, _ := tc.(map[string]any)
			tcIdx := int(tcMap["index"].(float64))
			tcID, _ := tcMap["id"].(string)
			fn, _ := tcMap["function"].(map[string]any)

			tb, exists := st.toolBlocks[tcIdx]
			if !exists {
				tb = &toolBlockState{anthropicIdx: st.nextBlockIdx, id: tcID}
				st.nextBlockIdx++
				st.toolBlocks[tcIdx] = tb
			}

			if tcID != "" {
				tb.id = tcID
			}
			if name, ok := fn["name"].(string); ok && name != "" {
				tb.name = name
			}

			if !tb.started && tb.id != "" {
				tb.started = true
				cbData, _ := json.Marshal(map[string]any{
					"type":  "content_block_start",
					"index": tb.anthropicIdx,
					"content_block": map[string]any{
						"type":  "tool_use",
						"id":    tb.id,
						"name":  tb.name,
						"input": map[string]any{},
					},
				})
				results = append(results, fmt.Sprintf("event: content_block_start\ndata: %s\n\n", string(cbData)))
			}

			if args, ok := fn["arguments"].(string); ok && args != "" {
				deltaData, _ := json.Marshal(map[string]any{
					"type":  "content_block_delta",
					"index": tb.anthropicIdx,
					"delta": map[string]any{
						"type":         "input_json_delta",
						"partial_json": args,
					},
				})
				results = append(results, fmt.Sprintf("event: content_block_delta\ndata: %s\n\n", string(deltaData)))
			}
		}
	}

	// Handle finish_reason
	if fr, ok := choice["finish_reason"].(string); ok && fr != "" && fr != "null" {
		switch fr {
		case "stop":
			st.finishReason = "end_turn"
		case "tool_calls":
			st.finishReason = "tool_use"
		case "length":
			st.finishReason = "max_tokens"
		}
	}

	// Track usage
	if usage, ok := obj["usage"].(map[string]any); ok {
		st.finalUsage = usage
	}

	return results
}
