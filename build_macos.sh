#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
pip install -r requirements-build.txt
pyinstaller --clean --noconfirm tft_assistant.spec

echo "Built: dist/TFT Assistant.app"
