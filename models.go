package main

import (
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"time"
)

var (
	modelCache       = map[string][]map[string]any{}
	modelCacheExpiry = map[string]time.Time{}
	modelLock        sync.RWMutex
	modelClient      = &http.Client{Timeout: 20 * time.Second}
	modelsInitialized bool
)

func DiscoverModels(cfg *Config) (zen, kilo []map[string]any) {
	modelLock.RLock()
	if modelsInitialized && time.Now().Before(modelCacheExpiry["kilo"]) {
		zen = modelCache["zen"]
		kilo = modelCache["kilo"]
		modelLock.RUnlock()
		return
	}
	modelLock.RUnlock()

	modelLock.Lock()
	defer modelLock.Unlock()

	if time.Now().Before(modelCacheExpiry["kilo"]) {
		return modelCache["zen"], modelCache["kilo"]
	}

	zen = fetchZenModels(cfg)
	kilo = fetchKiloFreeModels(cfg)

	modelCache["zen"] = zen
	modelCache["kilo"] = kilo
	modelCacheExpiry["zen"] = time.Now().Add(time.Duration(cfg.ModelDiscoveryTTL) * time.Second)
	modelCacheExpiry["kilo"] = time.Now().Add(time.Duration(cfg.ModelDiscoveryTTL) * time.Second)
	modelsInitialized = true

	return
}

func fetchZenModels(cfg *Config) []map[string]any {
	// Zen has no pricing info → use configured allowlist
	models := fetchJSONModels(cfg.ZenModelsURL)
	if len(models) == 0 {
		return fallbackModelList(cfg.ZenFallbackModels)
	}

	allowed := makeSet(cfg.ZenFallbackModels)
	var filtered []map[string]any
	for _, m := range models {
		id := strings.ToLower(str(m["id"]))
		if allowed[id] {
			filtered = append(filtered, m)
		}
	}
	if len(filtered) == 0 {
		return fallbackModelList(cfg.ZenFallbackModels)
	}
	return filtered
}

func fetchKiloFreeModels(cfg *Config) []map[string]any {
	models := fetchJSONModels(cfg.KiloModelsURL)
	if len(models) == 0 {
		return fallbackModelList(cfg.KiloFallbackModels)
	}

	var free []map[string]any
	for _, m := range models {
		if isFree, ok := m["isFree"].(bool); ok && isFree {
			free = append(free, m)
		}
	}
	if len(free) == 0 {
		return fallbackModelList(cfg.KiloFallbackModels)
	}
	return free
}

func fetchJSONModels(url string) []map[string]any {
	resp, err := modelClient.Get(url)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()

	var data any
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return nil
	}

	switch d := data.(type) {
	case []any:
		var models []map[string]any
		for _, item := range d {
			if m, ok := item.(map[string]any); ok {
				models = append(models, m)
			}
		}
		return models
	case map[string]any:
		if arr, ok := d["data"].([]any); ok {
			var models []map[string]any
			for _, item := range arr {
				if m, ok := item.(map[string]any); ok {
					models = append(models, m)
				}
			}
			return models
		}
	}
	return nil
}

func fallbackModelList(names []string) []map[string]any {
	var list []map[string]any
	for _, n := range names {
		list = append(list, map[string]any{"id": strings.TrimSpace(n)})
	}
	return list
}

func WarmModelCache(cfg *Config) {
	go func() {
		DiscoverModels(cfg)
		Info.Printf("model cache warmed (%d zen, %d kilo models)", len(modelCache["zen"]), len(modelCache["kilo"]))
	}()
}

func makeSet(items []string) map[string]bool {
	s := make(map[string]bool, len(items))
	for _, item := range items {
		s[strings.ToLower(strings.TrimSpace(item))] = true
	}
	return s
}
