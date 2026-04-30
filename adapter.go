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

// UpstreamResult holds the raw upstream response.
type UpstreamResult struct {
	StatusCode int
	Headers    map[string]string
	Body       []byte
}
