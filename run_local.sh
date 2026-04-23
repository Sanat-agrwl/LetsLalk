#!/bin/bash
# Quick local run (no Docker needed — good for dev/testing)
set -e

if [ ! -f .env ]; then
  echo "ERROR: .env file not found. Copy .env.example → .env and fill in keys."
  exit 1
fi

echo "Installing dependencies..."
pip install -r requirements.txt -q

echo "Starting agent at http://localhost:8765 ..."
uvicorn src.main:app --host 0.0.0.0 --port 8765 --log-level info --ws-ping-interval 20 --ws-ping-timeout 60
