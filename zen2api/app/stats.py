"""Statistics tracking for zen2api."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config
from .logger import get_logger

logger = get_logger("stats")


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _empty_tokens() -> dict[str, int]:
    return {"input": 0, "output": 0, "cached_input": 0}


def _empty_counters() -> dict[str, int]:
    return {
        "requests": 0,
        "success": 0,
        "auth_error": 0,
        "rate_limited": 0,
        "upstream_error": 0,
        "other_error": 0,
    }


def _empty_daily_entry() -> dict[str, Any]:
    return {
        "requests": _empty_counters(),
        "tokens": _empty_tokens(),
        "by_model": {},
    }


def _status_to_key(status_code: int) -> str:
    if status_code >= 200 and status_code < 300:
        return "success"
    if status_code == 401 or status_code == 403:
        return "auth_error"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "upstream_error"
    return "other_error"


class Stats:
    def __init__(self, file_path: str):
        self._file_path = file_path
        self._lock = threading.Lock()
        self._data = self._load()

    def record_request(self, model: str, status_code: int) -> None:
        with self._lock:
            key = _status_to_key(status_code)
            self._ensure_today()
            self._ensure_model(model)

            today_str = date.today().isoformat()
            self._data["total"]["requests"]["requests"] += 1
            self._data["total"]["requests"][key] += 1
            self._data["total"]["by_model"][model]["requests"] += 1
            self._data["total"]["by_model"][model][key] += 1

            self._data["daily"][today_str]["requests"]["requests"] += 1
            self._data["daily"][today_str]["requests"][key] += 1
            self._data["daily"][today_str]["by_model"][model]["requests"] += 1
            self._data["daily"][today_str]["by_model"][model][key] += 1

            self._save()

    def record_tokens(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int,
    ) -> None:
        with self._lock:
            self._ensure_today()
            self._ensure_model(model)
            self._ensure_daily_entry()
            self._ensure_daily_model(model)

            today_str = date.today().isoformat()

            for container in [
                self._data["total"]["tokens"],
                self._data["total"]["by_model"][model]["tokens"],
                self._data["daily"][today_str]["tokens"],
                self._data["daily"][today_str]["by_model"][model]["tokens"],
            ]:
                container["input"] += input_tokens
                container["output"] += output_tokens
                container["cached_input"] = max(
                    0, container.get("cached_input", 0) + cached_input_tokens
                )

            self._save()

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def reset(self) -> None:
        with self._lock:
            self._data = self._make_empty()
            self._save()
            logger.info("Stats reset completed")

    def summary(self) -> str:
        with self._lock:
            total_req = self._data["total"]["requests"]
            today_req = self._data["daily"].get(
                date.today().isoformat(), _empty_daily_entry()
            )["requests"]

            total_tokens = self._data["total"]["tokens"]
            today_tokens = self._data["daily"].get(
                date.today().isoformat(), _empty_daily_entry()
            )["tokens"]

            total_hit_rate = self._cache_hit_rate(total_tokens)
            today_hit_rate = self._cache_hit_rate(today_tokens)

            return (
                f"Stats summary | total_requests={total_req['requests']}"
                f" (success={total_req['success']}, rate_limited={total_req['rate_limited']}, "
                f"auth_error={total_req['auth_error']}, upstream_error={total_req['upstream_error']}, "
                f"other_error={total_req['other_error']})"
                f" | total_tokens(input={total_tokens['input']}, "
                f"cached_input={total_tokens['cached_input']}, "
                f"output={total_tokens['output']}, cache_hit_rate={total_hit_rate:.1%})"
                f" | today_requests={today_req['requests']}"
                f" today_tokens(input={today_tokens['input']}, "
                f"cached_input={today_tokens['cached_input']}, "
                f"output={today_tokens['output']}, cache_hit_rate={today_hit_rate:.1%})"
            )

    @staticmethod
    def _cache_hit_rate(tokens: dict[str, int]) -> float:
        inp = tokens.get("input", 0)
        if inp <= 0:
            return 0.0
        cached = tokens.get("cached_input", 0)
        return min(1.0, cached / inp)

    @staticmethod
    def _make_empty() -> dict[str, Any]:
        return {
            "total": {
                "requests": _empty_counters(),
                "tokens": _empty_tokens(),
                "by_model": {},
            },
            "daily": {},
        }

    def _prune_daily_buckets(self) -> None:
        max_buckets = 90
        sorted_dates = sorted(self._data["daily"].keys())
        remove_count = max(0, len(sorted_dates) - max_buckets)
        for d in sorted_dates[:remove_count]:
            self._data["daily"].pop(d, None)

    def _ensure_today(self) -> None:
        today_str = date.today().isoformat()
        if today_str not in self._data["daily"]:
            self._data["daily"][today_str] = _empty_daily_entry()
            self._prune_daily_buckets()

    def _ensure_model(self, model: str) -> None:
        if model not in self._data["total"]["by_model"]:
            self._data["total"]["by_model"][model] = {
                "requests": _empty_counters(),
                "tokens": _empty_tokens(),
            }

    def _ensure_daily_entry(self) -> None:
        today_str = date.today().isoformat()
        if today_str not in self._data["daily"]:
            self._data["daily"][today_str] = _empty_daily_entry()

    def _ensure_daily_model(self, model: str) -> None:
        today_str = date.today().isoformat()
        if today_str not in self._data["daily"]:
            self._data["daily"][today_str] = _empty_daily_entry()
        if model not in self._data["daily"][today_str]["by_model"]:
            self._data["daily"][today_str]["by_model"][model] = {
                "requests": _empty_counters(),
                "tokens": _empty_tokens(),
            }

    def _save(self) -> None:
        try:
            path = Path(self._file_path)
            dir_name = path.parent
            dir_name.mkdir(parents=True, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", prefix=".stats.", dir=str(dir_name)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, str(path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as exc:
            logger.error("Failed to save stats | error=%s", exc)

    def _load(self) -> dict[str, Any]:
        path = Path(self._file_path)
        if not path.exists():
            logger.info(
                "Stats file not found, initializing empty stats | path=%s",
                self._file_path,
            )
            return self._make_empty()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("Stats loaded | path=%s", self._file_path)
            return self._normalize_loaded_data(data)
        except json.JSONDecodeError:
            logger.warning(
                "Stats file format invalid, reinitializing | path=%s",
                self._file_path,
            )
            return self._make_empty()
        except Exception as exc:
            logger.warning(
                "Failed to read stats file, reinitializing | path=%s | error=%s",
                self._file_path,
                exc,
            )
            return self._make_empty()

    def _normalize_loaded_data(self, data: dict[str, Any]) -> dict[str, Any]:
        result = self._make_empty()

        if not isinstance(data, dict):
            return result

        total = data.get("total", {})
        if isinstance(total, dict):
            result["total"]["requests"] = self._normalize_requestss(
                total.get("requests")
            )
            result["total"]["tokens"] = self._normalize_tokens(total.get("tokens"))
            result["total"]["by_model"] = self._normalize_by_model(
                total.get("by_model")
            )

        daily = data.get("daily", {})
        if isinstance(daily, dict):
            result["daily"] = self._normalize_daily(daily)

        return result

    def _normalize_requestss(
        self, data: Any
    ) -> dict[str, int]:
        result = _empty_counters()
        if isinstance(data, dict):
            for key in result:
                if key in data:
                    result[key] = _to_int(data[key])
        return result

    def _normalize_tokens(self, data: Any) -> dict[str, int]:
        result = _empty_tokens()
        if isinstance(data, dict):
            for key in result:
                if key in data:
                    result[key] = _to_int(data[key])
        return result

    def _normalize_by_model(
        self, data: Any
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if isinstance(data, dict):
            for model, model_data in data.items():
                if isinstance(model_data, dict):
                    result[model] = {
                        "requests": self._normalize_requestss(
                            model_data.get("requests")
                        ),
                        "tokens": self._normalize_tokens(model_data.get("tokens")),
                    }
        return result

    def _normalize_daily(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for date_str, day_data in data.items():
            if isinstance(day_data, dict):
                result[date_str] = {
                    "requests": self._normalize_requestss(day_data.get("requests")),
                    "tokens": self._normalize_tokens(day_data.get("tokens")),
                    "by_model": self._normalize_by_model(day_data.get("by_model")),
                }
        return result


stats = Stats(config.STATS_FILE)
