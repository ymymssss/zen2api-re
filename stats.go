package main

import (
	"encoding/json"
	"os"
	"sync"
	"time"
)

var (
	statsStartTime = time.Now()
	requestCount   int64
	errorCount     int64
	usageByKey     = map[string]*UsageRecord{}
	statsMu        sync.RWMutex
)

type UsageRecord struct {
	InputTokens  int     `json:"input_tokens"`
	OutputTokens int     `json:"output_tokens"`
	RequestCount int64   `json:"request_count"`
	LastAccess   float64 `json:"last_access"`
}

func StatsRecordRequest() {
	statsMu.Lock()
	requestCount++
	statsMu.Unlock()
}

func StatsRecordError() {
	statsMu.Lock()
	errorCount++
	statsMu.Unlock()
}

func RecordTokenUsage(body map[string]any) {
	usage, _ := body["usage"].(map[string]any)
	if usage == nil {
		return
	}
	in, _ := usage["input_tokens"].(float64)
	out, _ := usage["output_tokens"].(float64)
	if in == 0 && out == 0 {
		return
	}

	statsMu.Lock()
	defer statsMu.Unlock()
	rec, ok := usageByKey["default"]
	if !ok {
		rec = &UsageRecord{}
		usageByKey["default"] = rec
	}
	rec.InputTokens += int(in)
	rec.OutputTokens += int(out)
	rec.RequestCount++
	rec.LastAccess = float64(time.Now().Unix())
}

func UsageSnapshot() map[string]map[string]any {
	statsMu.RLock()
	defer statsMu.RUnlock()
	out := make(map[string]map[string]any, len(usageByKey))
	for k, r := range usageByKey {
		out[k] = map[string]any{
			"input_tokens":  r.InputTokens,
			"output_tokens": r.OutputTokens,
			"total_tokens":  r.InputTokens + r.OutputTokens,
			"request_count": r.RequestCount,
			"last_access":   r.LastAccess,
		}
	}
	return out
}

func WriteStatsFile(path string) error {
	payload := map[string]any{
		"uptime_seconds": time.Since(statsStartTime).Seconds(),
		"request_count":  requestCount,
		"error_count":    errorCount,
		"usage":          UsageSnapshot(),
		"timestamp":      float64(time.Now().Unix()),
	}
	data, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0644)
}

func StartStatsWriter(cfg *Config) {
	go func() {
		for {
			time.Sleep(time.Duration(cfg.StatsLogInterval) * time.Second)
			if err := WriteStatsFile(cfg.StatsFile); err != nil {
				Warning.Printf("failed to write stats: %v", err)
			}
		}
	}()
}
