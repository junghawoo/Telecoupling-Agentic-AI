# Telecoupling Agentic AI

An LLM-powered agentic platform for telecoupling environmental analysis. Researchers can query in natural language to run NatCap InVEST environmental models and QGIS geospatial operations — the agent composes and executes multi-step workflows at runtime via a ReAct loop.

---

## Architecture

```
Browser (http://localhost:5173)
        │
        ▼  SSE stream
FastAPI Backend (:8000)
  ├── LLM: LLaMA4 (Purdue GenAI Studio) or Gemini
  └── MCP Client
        ├── InVEST MCP Server (:54320) — 16 tools, 13 InVEST models
        └── QGIS MCP Server   (:54321) — 15 tools, 679+ algorithms
```

**ReAct Loop:** The LLM reasons about the user query, calls tools, observes results, and repeats until it can write a final answer — all streamed to the frontend in real time.

---

## System Requirements

| Requirement | Version | Notes |
|---|---|---|
| Ubuntu / WSL2 | 22.04+ | Linux required for QGIS headless |
| Python (conda) | 3.11+ | For backend + InVEST MCP |
| Python (system) | 3.12 | For QGIS MCP (`/usr/bin/python3`) |
| Node.js | 18+ | For frontend |
| QGIS | 3.34+ | Installed via `apt` |
| conda / mamba | any | Environment management |

---

## Installation

### 1. Install QGIS (system-level)

```bash
sudo apt-get update
sudo apt-get install -y qgis python3-qgis gdal-bin
```

### 2. Create conda environment

```bash
conda create -n telecoupling python=3.11 -y
conda activate telecoupling
```

### 3. Install Python dependencies

```bash
pip install -e ".[dev]"
```

### 4. Install MCP SDK for system Python (QGIS MCP requirement)

```bash
/usr/bin/python3 -m pip install --user "mcp[cli]>=1.0" python-dotenv
```

### 5. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

### 6. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set your LLM provider credentials:

```bash
# Choose provider: "purdue" or "gemini"
LLM_PROVIDER=purdue

# Purdue GenAI Studio
PURDUE_API_KEY=your-key-here
PURDUE_BASE_URL=https://genai.rcac.purdue.edu/api
PURDUE_MODEL=llama4:latest

# OR Google Gemini
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-2.0-flash
```

### 7. Download sample data

```bash
conda activate telecoupling
python download_sample_data.py
```

This downloads ~530 MB of InVEST sample datasets (13 models) and QGIS test rasters into `backend/data/sample-inputs/`.

---

## Running the Application

Start each service in a separate terminal. All four must be running simultaneously.

### Terminal 1 — InVEST MCP Server

```bash
conda activate telecoupling
cd mcp-servers/invest-mcp
python server.py
```

Expected output:
```
Starting InVEST MCP Server on port 54320 with 16 tools
Uvicorn running on http://127.0.0.1:54320
```

### Terminal 2 — QGIS MCP Server

```bash
cd mcp-servers/qgis-mcp
./run_qgis_mcp.sh
```

Expected output:
```
QGIS 3.34.x initialized — 9 providers, 679 algorithms
Starting QGIS MCP Server on port 54321 (15 tools)
Uvicorn running on http://127.0.0.1:54321
```

> The script forces `/usr/bin/python3` (system Python with PyQGIS) and sets `QT_QPA_PLATFORM=offscreen` for headless operation. Do not use the conda Python for this service.

### Terminal 3 — Backend

```bash
conda activate telecoupling
cd backend
python -m uvicorn app.main:app --port 8000
```

Expected output:
```
Agent ready – 31 tools available across ['invest-mcp', 'qgis-mcp']
Uvicorn running on http://127.0.0.1:8000
```

### Terminal 4 — Frontend

```bash
cd frontend
npm run dev
```

Expected output:
```
VITE ready in XXXms
Local: http://localhost:5173/
```

Open **http://localhost:5173** in your browser.

---

## Verifying the Setup

```bash
# Check backend health and tool count
curl http://localhost:8000/health

# Expected:
# {"status":"healthy","llm_provider":"purdue","tool_count":31,...}
```

```bash
# List all available tools
curl http://localhost:8000/agent/tools
```

---

## Project Structure

```
telecoupling-app/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── config.py          # Settings loaded from .env
│   │   │   ├── state.py           # App state (MCP client, agent instance)
│   │   │   └── dependencies.py    # FastAPI dependency injection
│   │   ├── models/
│   │   │   └── agent.py           # Pydantic models (ChatRequest, StreamEvent, etc.)
│   │   ├── routers/
│   │   │   ├── agent.py           # /agent/* endpoints (chat, tools, health)
│   │   │   ├── files.py           # /files/* endpoints (upload, list, delete)
│   │   │   └── jobs.py            # /jobs/* endpoints (history, status)
│   │   ├── services/
│   │   │   ├── agent.py           # TelecouplingAgent — ReAct loop (Purdue + Gemini)
│   │   │   ├── mcp_client.py      # MCPClient — connects to and calls MCP servers
│   │   │   ├── classifier.py      # Intent classification (analysis/geospatial/followup)
│   │   │   └── job_store.py       # In-memory job history
│   │   └── main.py                # FastAPI app, CORS, lifespan startup
│   ├── data/
│   │   ├── sample-inputs/         # InVEST sample datasets (downloaded separately)
│   │   ├── outputs/               # Model run outputs (git-ignored)
│   │   └── uploads/               # User-uploaded files (git-ignored)
│   └── tests/
│       ├── test_environment.py
│       ├── test_api.py
│       └── test_tools_full.py
│
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── ChatPanel.tsx       # Main chat interface, SSE stream handler
│       │   ├── MessageBubble.tsx   # Chat message rendering (markdown)
│       │   ├── ToolCallCard.tsx    # Tool call display (arguments + result)
│       │   ├── ThinkingIndicator.tsx # ReAct loop progress indicator
│       │   └── Sidebar.tsx         # Tools list, jobs, file upload
│       ├── App.tsx
│       ├── api.ts                  # streamChat() and API helpers
│       └── types.ts
│
├── mcp-servers/
│   ├── invest-mcp/
│   │   ├── server.py              # 13 InVEST model tools + 3 discovery tools
│   │   └── utils.py               # run_invest_model(), raster statistics helpers
│   └── qgis-mcp/
│       ├── server.py              # 15 QGIS geospatial tools
│       ├── utils.py               # init_qgis(), run_processing_algorithm()
│       └── run_qgis_mcp.sh        # Startup script (forces system Python)
│
├── download_sample_data.py        # Downloads InVEST + QGIS sample datasets
├── pyproject.toml                 # Python dependencies
├── .env.example                   # Environment variable template
└── .env                           # Active config (git-ignored — never commit)
```

---

## Available Tools

### InVEST MCP Server (16 tools)

| Tool | Model |
|---|---|
| `list_models` | Discover available models |
| `list_sample_data` | List sample input file paths by model |
| `get_sample_args` | Get ready-to-use arguments for a model |
| `run_carbon_storage` | Carbon Storage & Sequestration |
| `run_habitat_quality` | Habitat Quality |
| `run_sediment_delivery` | Sediment Delivery Ratio (SDR) |
| `run_nutrient_delivery` | Nutrient Delivery Ratio (NDR) |
| `run_seasonal_water_yield` | Seasonal Water Yield |
| `run_annual_water_yield` | Annual Water Yield |
| `run_forest_carbon_edge` | Forest Carbon Edge Effect |
| `run_coastal_blue_carbon` | Coastal Blue Carbon |
| `run_crop_production_percentile` | Crop Production (Percentile) |
| `run_crop_production_regression` | Crop Production (Regression) |
| `run_pollination` | Pollination |
| `run_habitat_risk_assessment` | Habitat Risk Assessment (HRA) |
| `run_recreation` | Recreation (Visitation Rate) |

### QGIS MCP Server (15 tools)

| Tool | Operation |
|---|---|
| `list_operations` | List all available QGIS tools |
| `list_algorithms` | Search 679+ QGIS Processing algorithms |
| `get_algorithm_details` | Full parameter info for any algorithm |
| `get_raster_info` | Raster metadata and band statistics |
| `get_vector_info` | Vector metadata and field schema |
| `reproject_raster` | Reproject raster to target CRS |
| `reproject_vector` | Reproject vector to target CRS |
| `clip_raster_by_mask` | Clip raster with vector mask |
| `clip_vector_by_extent` | Clip vector to bounding box |
| `buffer_vector` | Buffer features by distance |
| `vector_overlay` | Intersect / union / difference |
| `zonal_statistics` | Raster statistics within polygon zones |
| `raster_calculator` | Band math (GDAL raster calculator) |
| `render_map` | Render layers to PNG map image |
| `execute_processing` | Run any QGIS Processing algorithm by ID |

---

## API Reference

Base URL: `http://localhost:8000`

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | System health, LLM provider, tool count |
| `/docs` | GET | Swagger interactive API docs |
| `/agent/tools` | GET | List all 31 MCP tools |
| `/agent/health` | GET | Per-server liveness check |
| `/agent/chat` | POST | Streaming SSE chat (ReAct loop) |
| `/agent/chat/sync` | POST | Synchronous chat |
| `/files/upload` | POST | Upload geospatial file |
| `/files` | GET | List uploaded files |
| `/files/{filename}` | DELETE | Delete uploaded file |
| `/jobs` | GET | Recent job history |
| `/jobs/{job_id}` | GET | Job detail and tool call log |

### Streaming Chat Example

```bash
curl -X POST http://localhost:8000/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Run carbon storage model and interpret results"}]}'
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `purdue` | LLM backend: `purdue` or `gemini` |
| `PURDUE_API_KEY` | — | Purdue GenAI Studio API key |
| `PURDUE_BASE_URL` | `https://genai.rcac.purdue.edu/api` | Purdue API endpoint |
| `PURDUE_MODEL` | `llama4:latest` | Model name |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model name |
| `INVEST_MCP_PORT` | `54320` | InVEST MCP server port |
| `QGIS_MCP_PORT` | `54321` | QGIS MCP server port |
| `INVEST_SAMPLE_DATA_DIR` | `./data/sample-inputs` | Path to InVEST sample data |
| `INVEST_OUTPUT_DIR` | `./data/outputs` | Model output directory |
| `UPLOAD_DIR` | `./data/uploads` | User upload directory |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Running Tests

```bash
conda activate telecoupling
cd backend
pytest tests/ -v
```

> Tests require the InVEST MCP server to be running and sample data to be downloaded.

---

## Troubleshooting

**PROJ version mismatch on InVEST MCP startup**

The conda base environment may have an older PROJ database. The server auto-detects the correct path from `sys.executable`. If errors persist, set explicitly:

```bash
export PROJ_DATA=/path/to/miniconda3/envs/telecoupling/share/proj
export PROJ_LIB=$PROJ_DATA
python server.py
```

**QGIS MCP fails to start**

Ensure QGIS is installed via `apt`, not conda:

```bash
/usr/bin/python3 -c "import qgis; print('OK')"
```

If this fails:

```bash
sudo apt-get install --reinstall qgis python3-qgis
```

**Backend shows 0 tools connected**

Both MCP servers must be running before the backend starts. Start the servers first, then start the backend.

**Frontend port conflict**

If port 5173 is in use, Vite automatically tries 5174, 5175, etc. Check the terminal output for the actual port.

---

## LLM Providers

### Purdue GenAI Studio (default)
- Uses text-based ReAct parsing — tool calls extracted via regex from LLM output
- Models available: `llama4:latest`, `llama3.1`, and others via Purdue portal
- Requires a Purdue research computing account

### Google Gemini
- Uses native function calling API — more reliable tool invocation
- Switch by setting `LLM_PROVIDER=gemini` in `.env`
- Requires a Google AI Studio API key (free tier available)
