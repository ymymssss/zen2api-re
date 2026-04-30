package main

import (
	"sync"
	"time"
)

type TokenBucket struct {
	Rate       float64
	Burst      float64
	Tokens     float64
	LastRefill time.Time
	mu         sync.Mutex
}

func NewTokenBucket(rate, burst float64) *TokenBucket {
	return &TokenBucket{
		Rate:       rate,
		Burst:      burst,
		Tokens:     burst,
		LastRefill: time.Now(),
	}
}

func (tb *TokenBucket) TryAcquire() bool {
	tb.mu.Lock()
	defer tb.mu.Unlock()

	now := time.Now()
	elapsed := now.Sub(tb.LastRefill).Seconds()
	tb.Tokens = min(tb.Burst, tb.Tokens+elapsed*tb.Rate)
	tb.LastRefill = now

	if tb.Tokens >= 1.0 {
		tb.Tokens -= 1.0
		return true
	}
	return false
}

type RateLimiter struct {
	DefaultRate  float64
	DefaultBurst float64
	buckets      map[string]*TokenBucket
	mu           sync.RWMutex
}

var GlobalRateLimiter *RateLimiter

func NewRateLimiter(rate, burst float64) *RateLimiter {
	return &RateLimiter{
		DefaultRate:  rate,
		DefaultBurst: burst,
		buckets:      make(map[string]*TokenBucket),
	}
}

func (rl *RateLimiter) TryAcquire(key string) bool {
	rl.mu.RLock()
	tb, ok := rl.buckets[key]
	rl.mu.RUnlock()

	if !ok {
		rl.mu.Lock()
		tb = NewTokenBucket(rl.DefaultRate, rl.DefaultBurst)
		rl.buckets[key] = tb
		rl.mu.Unlock()
	}
	return tb.TryAcquire()
}

func (rl *RateLimiter) GetBuckets() map[string]map[string]any {
	rl.mu.RLock()
	defer rl.mu.RUnlock()
	out := make(map[string]map[string]any, len(rl.buckets))
	for k, tb := range rl.buckets {
		tb.mu.Lock()
		out[k] = map[string]any{
			"tokens": tb.Tokens,
			"rate":   tb.Rate,
			"burst":  tb.Burst,
		}
		tb.mu.Unlock()
	}
	return out
}

func InitRateLimiter(cfg *Config) {
	GlobalRateLimiter = NewRateLimiter(cfg.NonModalRPS, cfg.NonModalRPS)
}
