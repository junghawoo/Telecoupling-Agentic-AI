# invest-mcp — InVEST MCP Server

A **self-contained** [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes **27 NatCap InVEST environmental models** as callable tools for AI agents (Claude Code, Claude Desktop, or any MCP-compatible client).

---

## Contents

- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Using with VS Code](#using-with-vs-code)
- [Using with Claude Desktop](#using-with-claude-desktop)
- [Configuration](#configuration)
- [Available tools](#available-tools)
- [Adding Nan's new tools with `nan_to_mcp.py`](#adding-nans-new-tools-with-nan_to_mcppy)
- [Refreshing the docs cache](#refreshing-the-docs-cache)
- [Project layout](#project-layout)

---

## What it does

Each InVEST model is exposed as an `@mcp.tool()` decorated function. An AI agent can:

1. Call `list_models()` to discover all available models.
2. Call `get_sample_args("model_name")` to get exact parameter names and sample file paths.
3. Call `run_<model>(...)` to execute the model and receive structured JSON results — output file paths + raster statistics.

---

## Quick start

### Only requirement: conda (Anaconda or Miniconda)

Everything else is handled automatically.

> **Why conda?** `natcap.invest` depends on GDAL, a C geospatial library.
> PyPI's `gdal` package requires a matching `libgdal` to already be installed
> system-wide — the versions must match exactly. conda-forge bundles both
> together and guarantees they match. **Never `pip install natcap.invest` or
> `pip install gdal` directly** — this is the most common setup failure.

### One-command setup (recommended)

Run this from anywhere inside the repo:

```bash
bash mcp-servers/invest-mcp/setup.sh
```

That single script:
1. Creates a `telecoupling` conda environment (Python 3.11) — skipped if it exists
2. Installs `natcap.invest` + GDAL via conda-forge
3. Installs the remaining deps (`mcp`, `dotenv`, etc.) with pip
4. Writes `.claude/settings.json` — picked up by the Claude Code extension in VS Code
5. Writes `.vscode/mcp.json` — picked up by VS Code's native MCP support
6. Verifies all imports

Re-running `setup.sh` is safe — it skips steps that are already done.

### After setup: run the server

```bash
# SSE network server (port 54320) — for standalone use or multiple clients
conda activate telecoupling
invest-mcp

# Or stdio (for VS Code — usually launched automatically, no manual start needed)
conda activate telecoupling
python mcp-servers/invest-mcp/server.py --transport stdio
```

### Manual setup (if you prefer step-by-step)

<details>
<summary>Click to expand</summary>

```bash
# 1. Create conda env
conda create -n telecoupling python=3.11 -y
conda activate telecoupling

# 2. Install GDAL + natcap.invest (must use conda-forge, not pip)
conda install -c conda-forge natcap.invest -y

# 3. Install pure-Python deps + register the entry point
cd mcp-servers/invest-mcp
pip install -e .

# 4. Verify
python -c "import natcap.invest; print('natcap.invest', natcap.invest.__version__)"
python -c "from osgeo import gdal; print('GDAL', gdal.__version__)"
invest-mcp --help
```

Then write the config files manually — see [Using with VS Code](#using-with-vs-code).

</details>

---

## Configuration

All settings are read from `.env` in this directory (falls back to the repo-root `.env`).

| Variable | Default | Description |
|---|---|---|
| `INVEST_MCP_PORT` | `54320` | Port for the SSE transport |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `INVEST_OUTPUT_DIR` | `./data/outputs` | Where model output workspaces are created |
| `INVEST_SAMPLE_DATA_DIR` | `./data/sample-inputs` | Sample input data (run `download_sample_data.py` at repo root) |
| `MODEL_DATA_PATH` | *(empty)* | Path to InVEST model-data directory — required for crop production models. [Download here.](https://storage.googleapis.com/releases.naturalcapitalproject.org/invest/3.14.0/InVEST_3.14.0_model_data.zip) |

---

## Available tools

### Discovery tools (call these first)

| Tool | Description |
|---|---|
| `list_models()` | List all 24 InVEST models with descriptions |
| `get_sample_args(model_name)` | Get ready-to-use parameter dict with sample file paths |
| `list_sample_data()` | List all available sample input files by model |

### InVEST model tools

#### Coastal / Marine
| Tool | Model |
|---|---|
| `run_coastal_blue_carbon(...)` | Coastal Blue Carbon — carbon sequestration in mangroves/seagrass/marshes |
| `run_coastal_vulnerability(...)` | Coastal Vulnerability — shoreline exposure to waves, SLR, geomorphology |
| `run_wave_energy(...)` | Wave Energy Production — biophysical + valuation |
| `run_offshore_wind_energy(...)` | Offshore Wind Energy — power density + NPV |

#### Water / Hydrology
| Tool | Model |
|---|---|
| `run_annual_water_yield(...)` | Annual Water Yield — Budyko curve watershed model |
| `run_seasonal_water_yield(...)` | Seasonal Water Yield — quickflow + baseflow |
| `run_nutrient_delivery_ratio(...)` | Nutrient Delivery Ratio — N/P loading to streams |
| `run_sediment_delivery_ratio(...)` | Sediment Delivery Ratio — USLE erosion + delivery |
| `run_delineateit(...)` | DelineateIt — watershed delineation from DEM |
| `run_routedem(...)` | RouteDEM — flow direction, accumulation, slope |

#### Terrestrial / Carbon
| Tool | Model |
|---|---|
| `run_carbon_storage(...)` | Carbon Storage & Sequestration |
| `run_forest_carbon_edge_effect(...)` | Forest Carbon Edge Effect — tropical edge degradation |
| `run_habitat_quality(...)` | Habitat Quality — degradation from threats |
| `run_habitat_risk_assessment(...)` | Habitat Risk Assessment — stressor exposure/consequence |
| `run_pollination(...)` | Crop Pollination — wild pollinator supply |

#### Agriculture / Land Use
| Tool | Model |
|---|---|
| `run_crop_production_percentile(...)` | Crop Production (Percentile) — 172 crops |
| `run_crop_production_regression(...)` | Crop Production (Regression) — fertilizer-based |
| `run_scenario_gen_proximity(...)` | Scenario Generator — proximity-based LULC conversion |

#### Urban
| Tool | Model |
|---|---|
| `run_urban_cooling(...)` | Urban Cooling — green space heat mitigation |
| `run_urban_flood(...)` | Urban Flood Risk Mitigation — curve number stormwater |
| `run_urban_nature_access(...)` | Urban Nature Access — proximity to green space |
| `run_urban_stormwater(...)` | Urban Stormwater Retention — runoff + water quality |

#### Scenic / Recreation
| Tool | Model |
|---|---|
| `run_scenic_quality(...)` | Scenic Quality — viewshed impact of structures |
| `run_recreation(...)` | Visitation Rate — recreation demand |

---

## Using with VS Code

### The easy way: run `setup.sh` first

`setup.sh` writes the config files automatically with the correct conda Python path.
After running it, just open the project folder in VS Code — no manual editing needed.

```bash
bash mcp-servers/invest-mcp/setup.sh   # one-time
code .                                  # open project — MCP auto-registers
```

Verify it worked: **Command Palette** (`⌘⇧P`) → `MCP: List Servers` → should show `invest-mcp`.

---

### What `setup.sh` writes (for reference)

**`.claude/settings.json`** — read by the Claude Code extension:

```json
{
  "mcpServers": {
    "invest-mcp": {
      "command": "/Users/you/anaconda3/envs/telecoupling/bin/python",
      "args": [
        "/path/to/repo/mcp-servers/invest-mcp/server.py",
        "--transport", "stdio"
      ],
      "env": {
        "INVEST_OUTPUT_DIR": "/path/to/repo/data/outputs",
        "INVEST_SAMPLE_DATA_DIR": "/path/to/repo/data/sample-inputs"
      }
    }
  }
}
```

**`.vscode/mcp.json`** — read by VS Code's native MCP support:

```json
{
  "servers": {
    "invest-mcp": {
      "type": "stdio",
      "command": "/Users/you/anaconda3/envs/telecoupling/bin/python",
      "args": [
        "${workspaceFolder}/mcp-servers/invest-mcp/server.py",
        "--transport", "stdio"
      ],
      "env": {
        "INVEST_OUTPUT_DIR": "${workspaceFolder}/data/outputs",
        "INVEST_SAMPLE_DATA_DIR": "${workspaceFolder}/data/sample-inputs"
      }
    }
  }
}
```

> **Key points:**
> - Use the **full absolute path** to the conda env's Python — never `python` or `invest-mcp` alone, because VS Code doesn't inherit your shell's conda activation.
> - `--transport stdio` is required for VS Code. The server then uses stdin/stdout instead of a port; VS Code manages the process lifecycle.
> - `setup.sh` detects all paths automatically and fills them in.

### Transport modes

| Mode | How it's used | Started by |
|---|---|---|
| `stdio` | VS Code, Claude Code, Claude Desktop | The MCP client (auto) |
| `sse` | Standalone network server | You, manually |

```bash
# SSE: start once, any number of clients can connect
conda activate telecoupling
invest-mcp                           # listens on port 54320

# stdio: VS Code starts this automatically — you don't run it manually
python server.py --transport stdio
```

You can also set the transport via environment variable instead of a flag:
```bash
export INVEST_MCP_TRANSPORT=stdio
python server.py
```

---

## Using with Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "invest-mcp": {
      "command": "/Users/you/anaconda3/envs/telecoupling/bin/python",
      "args": [
        "/path/to/repo/mcp-servers/invest-mcp/server.py",
        "--transport", "stdio"
      ],
      "env": {
        "INVEST_OUTPUT_DIR": "/path/to/repo/data/outputs",
        "INVEST_SAMPLE_DATA_DIR": "/path/to/repo/data/sample-inputs"
      }
    }
  }
}
```

Replace `/Users/you/anaconda3/envs/telecoupling/bin/python` with the output of:
```bash
conda activate telecoupling && which python
```

---

## Adding Nan's new tools with `nan_to_mcp.py`

`nan_to_mcp.py` is a **code converter** that reads Nan's async Python tool modules and generates FastMCP `@mcp.tool()` functions for `server.py`.

### The problem it solves

Nan writes tools in this style (her CSIS backend format):
```python
async def run_urban_cooling(params: dict, session_id: str, task_id: str, progress_callback):
    model_data_path = params.get("model_data_path") or settings.MODEL_DATA_PATH
    ...
```

The MCP server needs them in this style (Shubham's FastMCP format):
```python
@mcp.tool()
def run_urban_cooling(lulc_raster_path: str, t_ref: float, uhi_max: float, ...) -> str:
    """Estimate the cooling effect of urban green spaces..."""
    ...
```

`nan_to_mcp.py` does that translation automatically — including extracting official parameter descriptions from [InVEST readthedocs](https://invest.readthedocs.io/en/latest/models.html).

---

### Workflow: Nan adds or changes a tool

```
Nan edits/adds a file in PythonScripts_TCToolbox/tools/
              ↓
    python nan_to_mcp.py tools/ --sync server.py --dry-run   ← preview
              ↓
    python nan_to_mcp.py tools/ --sync server.py              ← apply
              ↓
    server.py updated — restart invest-mcp
```

---

### Commands

#### `--sync` — the main command (handles both new tools and updates)

```bash
python nan_to_mcp.py /path/to/Nan/tools/  --sync server.py
```

For every tool file in Nan's directory it decides:

| Status | Condition | Action |
|---|---|---|
| `[+] new` | Function not yet in `server.py` | Appended before the entry-point block |
| `[~] changed` | Params added, removed, or types/defaults differ | Old function **replaced in-place** |
| `[=] unchanged` | Signature identical | Skipped — no noise |

**Signature change** means any of: parameter added or removed, type annotation changed, default value changed. The exact diff is shown:

```
[~] coastal_vulnerability.py → run_coastal_vulnerability()  CHANGED: +{wave_period_table_path}
[~] urban_cooling.py         → run_urban_cooling()          CHANGED: ~{cc_method, t_ref}
[+] new_model.py             → run_new_model()              (new, would append)
[=] routedem.py                                             (unchanged)
```

#### `--dry-run` — preview without writing

```bash
python nan_to_mcp.py /path/to/Nan/tools/  --sync server.py  --dry-run
```

Shows exactly what would change. Does not modify `server.py`.

```
[dry-run] 3 change(s) would be applied — rerun without --dry-run to apply
```

#### `--append-to` — new tools only (no updates)

```bash
python nan_to_mcp.py /path/to/Nan/tools/  --append-to server.py
```

Only appends tools that do not yet exist in `server.py`. Tools with changed signatures are **silently skipped**. Use `--sync` if you want updates too.

#### `--output` — write to a separate file (preview or staging)

```bash
python nan_to_mcp.py /path/to/Nan/tools/  --output new_tools_preview.py
```

Generates the tool functions to a separate file instead of modifying `server.py`. Useful for reviewing before applying.

#### Single file — convert just one tool

```bash
# Preview
python nan_to_mcp.py /path/to/Nan/tools/urban_cooling.py

# Sync just one file
python nan_to_mcp.py /path/to/Nan/tools/urban_cooling.py  --sync server.py
```

#### `--skip` — exclude specific modules

```bash
python nan_to_mcp.py /path/to/Nan/tools/  --sync server.py  \
  --skip render_tif read_file network_analysis
```

#### `--dry-run` with `--append-to`

```bash
python nan_to_mcp.py /path/to/Nan/tools/  --append-to server.py  --dry-run
```

---

### What the converter handles automatically

`nan_to_mcp.py` parses Nan's source files with Python's `ast` module and handles all patterns found in her codebase:

| Pattern in Nan's code | Generated MCP param |
|---|---|
| `params["dem_path"]` | `dem_path: str` — required, no default |
| `params.get("results_suffix", "")` | `results_suffix: str = ""` — optional |
| `int(params["model_resolution"])` | `model_resolution: int` — required int |
| `cc_method = params.get("cc_method", "factors")` | `cc_method: str = "factors"` — local var traced back |
| `if snap_points: invest_args["flow_threshold"] = ...` | `flow_threshold: int = 1000` — conditional block included |
| `for opt_key in ("key1", "key2", ...):` | `key1: str = "", key2: str = ""` — for-loop pattern |

**Docstrings** are generated from three sources (priority order):
1. Official [InVEST readthedocs](https://invest.readthedocs.io/en/latest/models.html) parameter descriptions (from `invest_docs_cache.json`)
2. Nan's module-level docstring `Optional:` section hints
3. Parameter name pattern rules (`_path` → `"Path to ..."`, `do_` → `"If True, ..."`)

---

### Options reference

```
usage: nan_to_mcp.py [-h] [--output FILE] [--append-to SERVER_PY]
                     [--sync SERVER_PY] [--skip [STEM ...]] [--dry-run]
                     [--include-duplicates]
                     source

positional arguments:
  source                Path to a single .py file OR a directory of tool modules

options:
  -o, --output FILE     Write generated code to FILE (stdout if omitted)
  -a, --append-to SERVER_PY
                        Append NEW tools only — skips tools already in server.py
  --sync SERVER_PY      Full sync: append new + replace changed (recommended)
  -s, --skip STEM [STEM ...]
                        Module stems to skip (e.g. --skip render_tif read_file)
  --dry-run             Preview changes without writing anything
  --include-duplicates  Also convert tools in the built-in ALREADY_IN_SERVER list
```

---

## Refreshing the docs cache

The converter uses `invest_docs_cache.json` for official parameter descriptions scraped from [invest.readthedocs.io](https://invest.readthedocs.io/en/latest/models.html). Refresh it when InVEST releases a new version:

```bash
# Requires: pip install requests beautifulsoup4
python fetch_invest_docs.py

# Check what's in the current cache
python fetch_invest_docs.py --check
```

The cache covers all 26 InVEST models (24 model tools + 2 preprocessors), with 10–22 parameter descriptions each.

---

## Project layout

```
invest-mcp/
├── server.py               Main MCP server — 27 @mcp.tool() functions
├── utils.py                Shared helpers: ensure_workspace, run_invest_model,
│                           collect_output_files, get_raster_summary
├── pyproject.toml          Standalone package config + CLI entry point
├── .env.example            Configuration template → copy to .env
│
├── nan_to_mcp.py           Converter: Nan's async tools → FastMCP @mcp.tool()
├── fetch_invest_docs.py    Scraper: readthedocs → invest_docs_cache.json
└── invest_docs_cache.json  Cached official parameter descriptions (26 models)
```

### Relationship between server.py and nan_to_mcp.py

```
Nan's tools/                nan_to_mcp.py              server.py
──────────────────          ─────────────────────      ──────────────────────
urban_cooling.py    ──►     AST parse + type            @mcp.tool()
coastal_vuln.py     ──►     inference + official   ──►  def run_urban_cooling(...)
routedem.py         ──►     docs lookup             ──►  def run_coastal_vulnerability(...)
...                         + diff against           ──►  def run_routedem(...)
                            existing server.py            ...
```

`server.py` is the **source of truth** for what the MCP server exposes. `nan_to_mcp.py` only writes to it when you explicitly run `--sync` or `--append-to` — it never auto-runs.

---

## Troubleshooting

### Setup errors

**`BackendUnavailable: Cannot import 'setuptools.backends.legacy'`**
Your setuptools is older than 69. Already fixed in `pyproject.toml` — make sure you have the latest version of this repo.

**`ModuleNotFoundError: No module named 'osgeo'`**
GDAL was not installed via conda. Run `conda install -c conda-forge natcap.invest` — never use pip for this.

**`ModuleNotFoundError: No module named 'natcap'`**
natcap.invest was not installed. Run `conda install -c conda-forge natcap.invest`.

**`Python bindings of GDAL X.Y.Z require at least libgdal X.Y.Z, but A.B.C was found`**
pip tried to install GDAL and found a version mismatch with the system libgdal.
Fix: `pip uninstall gdal`, then `conda install -c conda-forge natcap.invest`. Never mix pip and conda for GDAL.

### VS Code / MCP errors

**VS Code doesn't show `invest-mcp` in `MCP: List Servers`**
- Make sure you opened the **repo root folder** (`Telecoupling-Agentic-AI/`), not a subfolder.
- Check that `.vscode/mcp.json` and `.claude/settings.json` exist at the repo root. If not, re-run `setup.sh`.
- Reload VS Code: **Command Palette** → `Developer: Reload Window`.

**`spawn /path/to/python ENOENT` or `command not found`**
The Python path in the config file is wrong. Re-run `setup.sh` to regenerate it, or check the path with:
```bash
conda activate telecoupling && which python
```
Paste that exact path into `.claude/settings.json` and `.vscode/mcp.json`.

**Server starts but Claude says "no tools available" (SSE mode)**
Check that `INVEST_MCP_PORT` in `.env` matches the port in your client config (default: `54320`).

**`FileNotFoundError: [Errno 2] No such file or directory: 'Rscript'`**
R is not on PATH. Set `R_EXECUTABLE=/path/to/Rscript` in `.env` (only needed for the `network_analysis` tool).

**Crop production model fails with `model_data_path is invalid`**
Set `MODEL_DATA_PATH` in `.env` to the InVEST model-data directory. [Download here.](https://storage.googleapis.com/releases.naturalcapitalproject.org/invest/3.14.0/InVEST_3.14.0_model_data.zip)
