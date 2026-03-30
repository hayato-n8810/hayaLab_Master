#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
	echo "Error: python3 not found in PATH" >&2
	exit 127
fi

if ! command -v python >/dev/null 2>&1; then
	echo "Error: python not found in PATH (needed for slow_pattern.py as documented)" >&2
	exit 127
fi

echo "[1/4] pre_analysis"
python3 pre_analysis.py

echo "[2/4] diff"
python3 diff.py

echo "[3/4] slow_feature"
python3 slow_feature.py

echo "[4/4] slow_pattern"
python slow_pattern.py

echo "Done. Outputs are in ./outputs/"
