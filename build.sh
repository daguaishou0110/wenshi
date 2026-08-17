#!/usr/bin/env bash
set -euo pipefail
python -V
pip install --upgrade pip
pip install -r requirements.txt
python -c "import onnxruntime as ort; print('onnxruntime', ort.__version__)"
