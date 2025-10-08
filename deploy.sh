#!/usr/bin/env bash
set -euo pipefail
cd /opt/smartnis
git fetch origin main
git reset --hard origin/main
if [ -d ".venv" ]; then source .venv/bin/activate; fi
pip install -r requirements.txt
sudo systemctl restart smartnis
