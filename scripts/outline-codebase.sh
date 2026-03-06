#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:$PATH"

{
  tree . -I "_*" -I "data" -I "docs" -I "*.egg-info" -I __pycache__ -I tests -I build -I ".*" -L 5
  echo ""
} > CODEBASE.txt

git add CODEBASE.txt
