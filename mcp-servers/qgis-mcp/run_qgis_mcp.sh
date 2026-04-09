#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# Launch the QGIS MCP Server using system Python (PyQGIS bindings)
#
# Usage:
#   ./run_qgis_mcp.sh          # default port 54321
#   QGIS_MCP_PORT=9999 ./run_qgis_mcp.sh
# ─────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Force system Python (has PyQGIS via apt)
export PYTHON="/usr/bin/python3"

# Headless Qt — no display required
export QT_QPA_PLATFORM="offscreen"

# Use system PROJ database (avoids conda PROJ version mismatch)
export PROJ_LIB="/usr/share/proj"
export PROJ_DATA="/usr/share/proj"

# Ensure QGIS plugin path is available
export PYTHONPATH="/usr/share/qgis/python/plugins:${PYTHONPATH:-}"

# MCP SDK + dotenv installed via: /usr/bin/python3 -m pip install --user "mcp[cli]>=1.0" python-dotenv
# They live in ~/.local/lib/python3.12/site-packages (auto-discovered by system Python)

# Default port
export QGIS_MCP_PORT="${QGIS_MCP_PORT:-54321}"

echo "┌──────────────────────────────────────────────┐"
echo "│  QGIS MCP Server                             │"
echo "│  Port: ${QGIS_MCP_PORT}                              │"
echo "│  Python: $($PYTHON --version 2>&1)               │"
echo "│  PROJ_LIB: ${PROJ_LIB}                       │"
echo "└──────────────────────────────────────────────┘"

cd "$SCRIPT_DIR"
exec "$PYTHON" server.py
