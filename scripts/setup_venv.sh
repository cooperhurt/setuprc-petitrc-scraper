#!/usr/bin/env bash
set -euo pipefail

# Create venv in project root at .venv
python3 -m venv .venv

# Ensure pip/wheel/setuptools are current
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

# Install requirements
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
else
  echo "requirements.txt not found in project root"
fi

deactivate

echo "Virtualenv created at .venv and requirements installed."
echo "To use it, run: source .venv/bin/activate"
