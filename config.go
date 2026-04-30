package main

import (
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Host string
	Port string

	ZEN2APIEnabled bool
	APIKey         string

	ZenUpstreamURL       string
	ZenModelsURL         string
	ZenUserAgent         string
	ZenAnthropicVersion  string
	ZenFallbackModels    []string

	KiloUpstreamURL      string
	KiloModelsURL        string
	KiloFallbackModels   []string

	ModelDiscoveryTTL     int
	ModelDiscoveryTimeout int
	NonModalRPS           float64
	DefaultMaxTokens      int

	AnyRouterEnabled       bool
	AnyRouterPort          string
	AnyRouterCaptureEnabled bool
	AnyRouterCaptureDir    string

	LogLevel        string
	LogFile         string
	LogHealthCheck  bool
	StatsFile       string
	StatsLogInterval int
}

func LoadConfig() *Config {
	return &Config{
		Host: envStr("ZEN2API_HOST", "127.0.0.1"),
		Port: envStr("ZEN2API_PORT", "9015"),

		ZEN2APIEnabled: envBool("ZEN2API_ENABLED", true),
		APIKey:         envStr("ZEN2API_KEY", ""),

		ZenUpstreamURL:      envStr("ZEN_UPSTREAM_URL", "https://opencode.ai/zen/v1/messages"),
		ZenModelsURL:        envStr("ZEN_MODELS_URL", "https://opencode.ai/zen/v1/models"),
		ZenUserAgent:        envStr("ZEN_USER_AGENT", "ai-sdk/anthropic/2.0.65"),
		ZenAnthropicVersion: envStr("ZEN_ANTHROPIC_VERSION", "2023-06-01"),
		ZenFallbackModels:   splitEnv("ZEN2API_ZEN_MODELS", "minimax-m2.5-free"),

		KiloUpstreamURL:    envStr("KILO_UPSTREAM_URL", "https://api.kilo.ai/api/openrouter/chat/completions"),
		KiloModelsURL:      envStr("KILO_MODELS_URL", "https://api.kilo.ai/api/openrouter/models"),
		KiloFallbackModels: splitEnv("ZEN2API_KILO_MODELS",
			"kilo-auto/free,minimax/minimax-m2.5:free,inclusionai/ling-2.6-1t:free,"+
				"nvidia/nemotron-3-super-120b-a12b:free,stepfun/step-3.5-flash:free,"+
				"nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,poolside/laguna-xs.2:free,"+
				"poolside/laguna-m.1:free,tencent/hy3-preview:free,baidu/qianfan-ocr-fast:free,openrouter/free"),

		ModelDiscoveryTTL:     envInt("ZEN2API_MODEL_DISCOVERY_TTL_SECONDS", 900),
		ModelDiscoveryTimeout: envInt("ZEN2API_MODEL_DISCOVERY_TIMEOUT_SECONDS", 20),
		NonModalRPS:           envFloat("ZEN2API_NON_MODAL_RPS", 10),
		DefaultMaxTokens:      envInt("ZEN2API_DEFAULT_MAX_TOKENS", 8192),

		AnyRouterEnabled:        envBool("ZEN2API_ANYROUTER_ENABLED", false),
		AnyRouterPort:           envStr("ZEN2API_ANYROUTER_PORT", "18888"),
		AnyRouterCaptureEnabled: envBool("ZEN2API_ANYROUTER_CAPTURE_ENABLED", false),
		AnyRouterCaptureDir:     envStr("ZEN2API_ANYROUTER_CAPTURE_DIR", "/tmp/cc_anyrouter_proxy_captures"),

		LogLevel:         envStr("ZEN2API_LOG_LEVEL", "INFO"),
		LogFile:          envStr("ZEN2API_LOG_FILE", ""),
		LogHealthCheck:   envBool("ZEN2API_LOG_HEALTH_CHECK", false),
		StatsFile:        envStr("ZEN2API_STATS_FILE", "stats.json"),
		StatsLogInterval: envInt("ZEN2API_STATS_LOG_INTERVAL", 3600),
	}
}

func envStr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envBool(key string, fallback bool) bool {
	v := strings.ToLower(os.Getenv(key))
	if v == "1" || v == "true" || v == "yes" || v == "on" {
		return true
	}
	if v == "0" || v == "false" || v == "no" || v == "off" {
		return false
	}
	return fallback
}

func envInt(key string, fallback int) int {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return fallback
	}
	return n
}

func envFloat(key string, fallback float64) float64 {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	n, err := strconv.ParseFloat(v, 64)
	if err != nil {
		return fallback
	}
	return n
}

func splitEnv(key, fallback string) []string {
	v := os.Getenv(key)
	if v == "" {
		v = fallback
	}
	parts := strings.Split(v, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}
