package main

// AdaptedRequest is the result of adapting an incoming request for the upstream.
type AdaptedRequest struct {
	URL     string
	Method  string
	Headers map[string]string
	Body    any
}

// AdaptedResponse is the result of adapting an upstream response for the client.
type AdaptedResponse struct {
	StatusCode int
	Headers    map[string]string
	Body       any
}

// Adapter converts between protocol formats.
type Adapter interface {
	AdaptRequest(body map[string]any, headers map[string]string) *AdaptedRequest
	AdaptResponse(body map[string]any, statusCode int) *AdaptedResponse
}

// StreamAdapter is an optional interface for adapters that support SSE streaming transformation.
// When an Adapter implements StreamAdapter, proxyStreamRequest will use it to transform
// SSE events in real-time as they arrive from the upstream.
type StreamAdapter interface {
	// TransformSSEEvent transforms a single SSE event line (without "data: " prefix).
	// It returns the transformed lines to write to the client, or nil to skip.
	// The adapter maintains internal state across the stream.
	TransformSSEEvent(line string) []string

	// FinalizeSSE returns any final SSE events to write at stream end (e.g., [DONE]).
	FinalizeSSE() []string
}

// UpstreamResult holds the raw upstream response.
type UpstreamResult struct {
	StatusCode int
	Headers    map[string]string
	Body       []byte
}
