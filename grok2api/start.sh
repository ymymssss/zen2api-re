#!/bin/bash
cd "$(dirname "$0")"
python3 -m uvicorn app.main:app --host "${ZEN2API_GROK2API_HOST:-127.0.0.1}" --port "${ZEN2API_GROK2API_PORT:-8020}" --reload
