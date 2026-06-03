#!/usr/bin/env bash
# =============================================================================
# setup.sh — one-shot setup for invest-mcp
#
# What this script does:
#   1. Creates the 'telecoupling' conda environment (skips if it exists)
#   2. Installs natcap.invest + GDAL via conda-forge
#   3. Installs the remaining Python deps with pip
#   4. Writes .claude/settings.json  (Claude Code / VS Code Claude extension)
#   5. Writes .vscode/mcp.json       (VS Code native MCP support)
#
# Usage (run from anywhere inside the repo):
#   bash mcp-servers/invest-mcp/setup.sh
#
# Re-running is safe — existing conda env and config files are kept / updated.
# =============================================================================

set -euo pipefail

# ── Colours ─────────────────────────────────────────────────────────────────
GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; RESET="\033[0m"
ok()   { echo -e "${GREEN}✅  $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠   $*${RESET}"; }
err()  { echo -e "${RED}❌  $*${RESET}"; exit 1; }
step() { echo -e "\n${YELLOW}▶  $*${RESET}"; }

# ── Locate repo root (walk up until we find the .git directory) ──────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
while [[ "$REPO_ROOT" != "/" && ! -d "$REPO_ROOT/.git" ]]; do
    REPO_ROOT="$(dirname "$REPO_ROOT")"
done
[[ -d "$REPO_ROOT/.git" ]] || {
    # Not a git repo — fall back to the parent of invest-mcp (i.e. mcp-servers/../)
    REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
    warn "No .git found — assuming repo root is $REPO_ROOT"
}
ok "Repo root: $REPO_ROOT"

SERVER_DIR="$SCRIPT_DIR"
ENV_NAME="telecoupling"

# ── Find conda ───────────────────────────────────────────────────────────────
step "Locating conda"
CONDA_EXE=""
for candidate in \
    "$(command -v conda 2>/dev/null || true)" \
    "$HOME/anaconda3/bin/conda" \
    "$HOME/miniconda3/bin/conda" \
    "/opt/anaconda3/bin/conda" \
    "/opt/miniconda3/bin/conda"; do
    if [[ -x "$candidate" ]]; then
        CONDA_EXE="$candidate"
        break
    fi
done
[[ -n "$CONDA_EXE" ]] || err "conda not found. Install Anaconda or Miniconda first: https://docs.conda.io/en/latest/miniconda.html"
ok "conda: $CONDA_EXE"

CONDA_BASE="$("$CONDA_EXE" info --base 2>/dev/null)"
[[ -n "$CONDA_BASE" ]] || err "Could not determine conda base directory"

# ── Create / verify conda environment ────────────────────────────────────────
step "Checking conda environment '$ENV_NAME'"
if "$CONDA_EXE" env list | grep -qE "^${ENV_NAME}[[:space:]]"; then
    ok "Environment '$ENV_NAME' already exists — skipping creation"
else
    warn "Creating new conda environment '$ENV_NAME' (Python 3.11)..."
    "$CONDA_EXE" create -n "$ENV_NAME" python=3.11 -y
    ok "Environment '$ENV_NAME' created"
fi

# ── Install natcap.invest via conda-forge ────────────────────────────────────
step "Installing natcap.invest + GDAL via conda-forge"
echo "  (This may take several minutes on first install — GDAL has many C dependencies)"
if "$CONDA_EXE" run -n "$ENV_NAME" python -c "import natcap.invest" 2>/dev/null; then
    INVEST_VER=$("$CONDA_EXE" run -n "$ENV_NAME" python -c \
        "import natcap.invest; print(natcap.invest.__version__)" 2>/dev/null)
    ok "natcap.invest $INVEST_VER already installed"
else
    "$CONDA_EXE" install -n "$ENV_NAME" -c conda-forge natcap.invest -y
    ok "natcap.invest installed"
fi

# ── Install pip dependencies ─────────────────────────────────────────────────
step "Installing pip dependencies (mcp, dotenv, etc.)"
"$CONDA_EXE" run -n "$ENV_NAME" pip install -e "$SERVER_DIR" --quiet
ok "pip install complete"

# ── Derive paths ─────────────────────────────────────────────────────────────
PYTHON_PATH="$CONDA_BASE/envs/$ENV_NAME/bin/python"
[[ -x "$PYTHON_PATH" ]] || err "Python not found at $PYTHON_PATH"
ok "Python: $PYTHON_PATH"

OUTPUT_DIR="$REPO_ROOT/data/outputs"
SAMPLE_DIR="$REPO_ROOT/data/sample-inputs"
mkdir -p "$OUTPUT_DIR" "$SAMPLE_DIR"

# ── Write .claude/settings.json ──────────────────────────────────────────────
step "Writing .claude/settings.json (Claude Code / VS Code Claude extension)"
CLAUDE_DIR="$REPO_ROOT/.claude"
mkdir -p "$CLAUDE_DIR"
CLAUDE_CONFIG="$CLAUDE_DIR/settings.json"

cat > "$CLAUDE_CONFIG" <<EOF
{
  "mcpServers": {
    "invest-mcp": {
      "command": "$PYTHON_PATH",
      "args": [
        "$SERVER_DIR/server.py",
        "--transport",
        "stdio"
      ],
      "env": {
        "INVEST_OUTPUT_DIR": "$OUTPUT_DIR",
        "INVEST_SAMPLE_DATA_DIR": "$SAMPLE_DIR"
      }
    }
  }
}
EOF
ok "Written: $CLAUDE_CONFIG"

# ── Write .vscode/mcp.json ───────────────────────────────────────────────────
step "Writing .vscode/mcp.json (VS Code native MCP)"
VSCODE_DIR="$REPO_ROOT/.vscode"
mkdir -p "$VSCODE_DIR"
VSCODE_CONFIG="$VSCODE_DIR/mcp.json"

cat > "$VSCODE_CONFIG" <<EOF
{
  "servers": {
    "invest-mcp": {
      "type": "stdio",
      "command": "$PYTHON_PATH",
      "args": [
        "$SERVER_DIR/server.py",
        "--transport",
        "stdio"
      ],
      "env": {
        "INVEST_OUTPUT_DIR": "$OUTPUT_DIR",
        "INVEST_SAMPLE_DATA_DIR": "$SAMPLE_DIR"
      }
    }
  }
}
EOF
ok "Written: $VSCODE_CONFIG"

# ── Verify everything ────────────────────────────────────────────────────────
step "Verifying installation"
"$CONDA_EXE" run -n "$ENV_NAME" python -c "
from osgeo import gdal
import natcap.invest
print(f'  GDAL {gdal.__version__}')
print(f'  natcap.invest {natcap.invest.__version__}')
from mcp.server.fastmcp import FastMCP
print('  mcp (FastMCP) OK')
" && ok "All imports verified"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${RESET}"
echo -e "${GREEN}  Setup complete!${RESET}"
echo -e "${GREEN}════════════════════════════════════════════════════════${RESET}"
echo ""
echo "  Config files written:"
echo "    $CLAUDE_CONFIG"
echo "    $VSCODE_CONFIG"
echo ""
echo "  To test from the terminal:"
echo "    conda activate $ENV_NAME"
echo "    python $SERVER_DIR/server.py --transport stdio"
echo ""
echo "  To use in VS Code:"
echo "    1. Open folder: $REPO_ROOT"
echo "    2. Open Command Palette (⌘⇧P) → 'MCP: List Servers'"
echo "    3. You should see 'invest-mcp' listed"
echo ""
echo "  To run as a network server (SSE, port 54320):"
echo "    conda activate $ENV_NAME && invest-mcp"
echo ""
