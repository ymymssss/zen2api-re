package main

import (
	"encoding/json"
	"io/fs"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"
)

// ── Admin API ──────────────────────────────────────────────────────

func handleAdminStats(w http.ResponseWriter, r *http.Request) {
	statsMu.RLock()
	uptime := time.Since(statsStartTime).Seconds()
	statsMu.RUnlock()

	usage := UsageSnapshot()
	totalReqs := int64(0)
	totalIn, totalOut := 0, 0
	for _, u := range usage {
		totalReqs += u["request_count"].(int64)
		totalIn += u["input_tokens"].(int)
		totalOut += u["output_tokens"].(int)
	}

	writeJSON(w, 200, map[string]any{
		"uptime_seconds":     int(uptime),
		"uptime_display":     formatDuration(uptime),
		"total_requests":     totalReqs,
		"total_input_tokens":  totalIn,
		"total_output_tokens": totalOut,
		"total_tokens":       totalIn + totalOut,
		"active_keys":        len(usage),
		"usage_by_key":       usage,
	})
}

func handleAdminConfig(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case "GET":
		writeJSON(w, 200, map[string]any{"config": safeConfig()})
	case "POST":
		var updates map[string]any
		if err := json.NewDecoder(r.Body).Decode(&updates); err != nil {
			writeJSON(w, 400, map[string]any{"error": "invalid JSON"})
			return
		}
		writeJSON(w, 200, map[string]any{"message": "config updated at runtime is limited — restart to apply all changes"})
	default:
		writeJSON(w, 405, map[string]any{"error": "method not allowed"})
	}
}

func handleAdminRateLimits(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case "GET":
		buckets := GlobalRateLimiter.GetBuckets()
		writeJSON(w, 200, map[string]any{
			"default_rate":   GlobalRateLimiter.DefaultRate,
			"default_burst":  GlobalRateLimiter.DefaultBurst,
			"active_buckets": len(buckets),
			"buckets":        buckets,
		})
	case "POST":
		rate := r.URL.Query().Get("rate")
		burst := r.URL.Query().Get("burst")
		if rate != "" {
			if r, err := parseFloat(rate); err == nil && r > 0 {
				GlobalRateLimiter.DefaultRate = r
			}
		}
		if burst != "" {
			if b, err := parseInt(burst); err == nil && b > 0 {
				GlobalRateLimiter.DefaultBurst = float64(b)
			}
		}
		writeJSON(w, 200, map[string]any{"status": "ok"})
	default:
		writeJSON(w, 405, map[string]any{"error": "method not allowed"})
	}
}

func handleAdminModels(w http.ResponseWriter, r *http.Request) {
	zen, kilo := DiscoverModels(cfg)

	modelLock.RLock()
	zenExpiry := modelCacheExpiry["zen"]
	kiloExpiry := modelCacheExpiry["kilo"]
	modelLock.RUnlock()

	zenTTL := time.Until(zenExpiry).Seconds()
	kiloTTL := time.Until(kiloExpiry).Seconds()

	writeJSON(w, 200, map[string]any{
		"zen": map[string]any{
			"count":               len(zen),
			"models":              zen,
			"cache_ttl_remaining": max(0, zenTTL),
		},
		"kilo": map[string]any{
			"count":               len(kilo),
			"models":              kilo,
			"cache_ttl_remaining": max(0, kiloTTL),
		},
	})
}

func handleAdminModelsRefresh(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, map[string]any{"error": "method not allowed"})
		return
	}
	modelLock.Lock()
	modelCacheExpiry["zen"] = time.Time{}
	modelCacheExpiry["kilo"] = time.Time{}
	modelsInitialized = false
	modelLock.Unlock()
	zen, kilo := DiscoverModels(cfg)
	writeJSON(w, 200, map[string]any{
		"results": map[string]any{
			"zen":  map[string]any{"status": "ok", "count": len(zen)},
			"kilo": map[string]any{"status": "ok", "count": len(kilo)},
		},
	})
}

func handleAdminSystem(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]any{
		"version":  "1.0.0",
		"go":       runtime.Version(),
		"platform": runtime.GOOS + "/" + runtime.GOARCH,
		"pid":      os.Getpid(),
	})
}

// ── Captures ────────────────────────────────────────────────────────

func handleAdminCaptures(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case "GET":
		limit := 100
		if l := r.URL.Query().Get("limit"); l != "" {
			if n, err := parseInt(l); err == nil && n > 0 {
				limit = n
			}
		}
		captures := listCaptureFiles(limit)
		writeJSON(w, 200, map[string]any{"captures": captures})

	case "DELETE":
		n := deleteAllCaptures()
		writeJSON(w, 200, map[string]any{"deleted": n})

	default:
		writeJSON(w, 405, map[string]any{"error": "method not allowed"})
	}
}

func handleAdminCaptureDetail(w http.ResponseWriter, r *http.Request) {
	// Extract filename from path: /admin/api/captures/<filename>
	filename := strings.TrimPrefix(r.URL.Path, "/admin/api/captures/")
	if filename == "" {
		writeJSON(w, 400, map[string]any{"error": "missing filename"})
		return
	}

	switch r.Method {
	case "GET":
		data, err := os.ReadFile(filepath.Join(cfg.AnyRouterCaptureDir, filename))
		if err != nil {
			writeJSON(w, 404, map[string]any{"error": "capture not found"})
			return
		}
		var obj map[string]any
		json.Unmarshal(data, &obj)
		if obj == nil {
			obj = map[string]any{"raw": string(data)}
		}
		writeJSON(w, 200, obj)

	case "DELETE":
		if err := os.Remove(filepath.Join(cfg.AnyRouterCaptureDir, filename)); err != nil {
			writeJSON(w, 404, map[string]any{"error": "capture not found"})
			return
		}
		writeJSON(w, 200, map[string]any{"status": "ok"})

	default:
		writeJSON(w, 405, map[string]any{"error": "method not allowed"})
	}
}

func listCaptureFiles(limit int) []map[string]any {
	dir := cfg.AnyRouterCaptureDir
	entries, err := fs.ReadDir(os.DirFS(dir), ".")
	if err != nil {
		return nil
	}

	type capEntry struct {
		name    string
		modTime time.Time
	}

	var caps []capEntry
	for _, e := range entries {
		if e.IsDir() || !strings.HasPrefix(e.Name(), "capture_") {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		caps = append(caps, capEntry{name: e.Name(), modTime: info.ModTime()})
	}

	// Sort newest first
	sort.Slice(caps, func(i, j int) bool {
		return caps[i].modTime.After(caps[j].modTime)
	})

	if limit > len(caps) {
		limit = len(caps)
	}

	var result []map[string]any
	for i := 0; i < limit; i++ {
		entry := caps[i]
		item := map[string]any{
			"_filename": entry.name,
			"timestamp": entry.modTime.UnixMicro(),
		}

		// Read file to extract method, path, status
		data, err := os.ReadFile(filepath.Join(dir, entry.name))
		if err == nil {
			var obj map[string]any
			if json.Unmarshal(data, &obj) == nil {
				item["method"] = obj["method"]
				item["path"] = obj["path"]
				if s, ok := obj["status"].(float64); ok {
					item["response_status"] = int(s)
				}
			}
		}
		result = append(result, item)
	}
	return result
}

func deleteAllCaptures() int {
	dir := cfg.AnyRouterCaptureDir
	entries, err := os.ReadDir(dir)
	if err != nil {
		return 0
	}
	n := 0
	for _, e := range entries {
		if !e.IsDir() && strings.HasPrefix(e.Name(), "capture_") {
			if os.Remove(filepath.Join(dir, e.Name())) == nil {
				n++
			}
		}
	}
	return n
}

// ── Admin SPA ──────────────────────────────────────────────────────

func handleAdminUI(w http.ResponseWriter, r *http.Request) {
	if adminHTML == "" {
		writeJSON(w, 404, map[string]any{"error": "webui not embedded"})
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(adminHTML))
}

// ── Helpers ────────────────────────────────────────────────────────

func safeConfig() map[string]any {
	safe := map[string]any{
		"HOST": cfg.Host,
		"PORT": cfg.Port,
		"ZEN2API_ENABLED":            cfg.ZEN2APIEnabled,
		"API_KEY":                    maskKey(cfg.APIKey),
		"ZEN_UPSTREAM_URL":           cfg.ZenUpstreamURL,
		"ZEN_MODELS_URL":             cfg.ZenModelsURL,
		"ZEN2API_ZEN_MODELS":         cfg.ZenFallbackModels,
		"KILO_UPSTREAM_URL":          cfg.KiloUpstreamURL,
		"KILO_MODELS_URL":            cfg.KiloModelsURL,
		"ZEN2API_KILO_MODELS":        cfg.KiloFallbackModels,
		"MODEL_DISCOVERY_TTL":        cfg.ModelDiscoveryTTL,
		"MODEL_DISCOVERY_TIMEOUT":    cfg.ModelDiscoveryTimeout,
		"NON_MODAL_RPS":              cfg.NonModalRPS,
		"DEFAULT_MAX_TOKENS":         cfg.DefaultMaxTokens,
		"ANYROUTER_ENABLED":          cfg.AnyRouterEnabled,
		"ANYROUTER_PORT":             cfg.AnyRouterPort,
		"ANYROUTER_CAPTURE_ENABLED":  cfg.AnyRouterCaptureEnabled,
		"ANYROUTER_CAPTURE_DIR":      cfg.AnyRouterCaptureDir,
		"LOG_LEVEL":                  cfg.LogLevel,
		"LOG_HEALTH_CHECK":           cfg.LogHealthCheck,
		"STATS_FILE":                 cfg.StatsFile,
		"STATS_LOG_INTERVAL":         cfg.StatsLogInterval,
	}
	return safe
}

func maskKey(key string) string {
	if len(key) <= 4 {
		return "****"
	}
	return key[:4] + "****"
}

func formatDuration(s float64) string {
	sec := int64(s)
	m := sec / 60
	h := m / 60
	d := h / 24
	res := ""
	if d > 0 {
		res += itoa(int(d)) + "d "
	}
	if h%24 > 0 {
		res += itoa(int(h%24)) + "h "
	}
	if m%60 > 0 {
		res += itoa(int(m%60)) + "m "
	}
	res += itoa(int(sec%60)) + "s"
	return res
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	neg := false
	if n < 0 {
		neg = true
		n = -n
	}
	var buf [20]byte
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}

func parseFloat(s string) (float64, error) {
	n := float64(0)
	_, err := scanFloat(s, &n)
	return n, err
}

func scanFloat(s string, f *float64) (int, error) {
	neg := false
	i := 0
	if i < len(s) && s[i] == '-' {
		neg = true
		i++
	}
	whole := 0
	for i < len(s) && s[i] >= '0' && s[i] <= '9' {
		whole = whole*10 + int(s[i]-'0')
		i++
	}
	frac := float64(0)
	if i < len(s) && s[i] == '.' {
		i++
		div := 10.0
		for i < len(s) && s[i] >= '0' && s[i] <= '9' {
			frac += float64(s[i]-'0') / div
			div *= 10
			i++
		}
	}
	*f = float64(whole) + frac
	if neg {
		*f = -*f
	}
	return i, nil
}

func parseInt(s string) (int, error) {
	n := 0
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, &json.UnmarshalTypeError{}
		}
		n = n*10 + int(c-'0')
	}
	return n, nil
}
