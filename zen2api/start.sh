#!/bin/bash
cd "$(dirname "$0")"
python3 -m uvicorn app.main:app --host "${ZEN2API_HOST:-127.0.0.1}" --port "${ZEN2API_PORT:-9015}" --reload
