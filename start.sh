#!/bin/sh
set -eu
echo "[canopy] python=$(python -V 2>&1) port=${PORT:-8899}"
echo "[canopy] weights=$(ls -lh weights/best.onnx 2>/dev/null || echo MISSING)"
exec python -m uvicorn app:app --host 0.0.0.0 --port "${PORT:-8899}" --workers 1 --log-level info
