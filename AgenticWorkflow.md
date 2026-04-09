# Telecoupling AI — Demo & Exploration Guide

> A practical map of the codebase for walking your team through the project.
> Start here before the demo.

---

## 1. What This App Does

Users type natural-language questions in a chat interface.
An AI agent (LLM + tools) figures out what to do, calls the right tools, and streams its reasoning back live.

Two tool backends are connected:
- **InVEST** — 13 NatCap environmental models (carbon storage, habitat quality, water yield, etc.)
- **QGIS** — 15 geospatial operations (reproject, clip, buffer, zonal stats, render map, etc.)

Both are connected through **MCP (Model Context Protocol)** — a standard that lets the LLM call them like functions.

---

## 2. Start the Stack

```bash
# 1. Activate the conda environment
conda activate telecoupling

# 2. From telecoupling-app/ — start the backend (also spawns invest-mcp automatically)
cd telecoupling-app
python -m uvicorn app.main:app --port 8000 --app-dir backend

# 3. In a second terminal — start the frontend
cd telecoupling-app/frontend
npm run dev

# 4. Open the app
open http://localhost:5173

# 5. (Optional) QGIS tools — start with system Python in a third terminal
cd telecoupling-app/mcp-servers/qgis-mcp
./run_qgis_mcp.sh
```

> **Health check:** `curl http://localhost:8000/health`
> Should show `"status": "healthy"`, tool count, and connected MCP servers.

---

## 3. Project Layout

```
telecoupling-app/
│
├── backend/                        # Python FastAPI server
│   └── app/
│       ├── main.py                 # App entry point, lifespan, router registration
│       ├── core/
│       │   ├── config.py           # All settings (LLM keys, ports, paths) via .env
│       │   ├── state.py            # Singleton holders for MCPClient + Agent
│       │   └── dependencies.py     # FastAPI dependency injectors
│       ├── models/
│       │   └── agent.py            # Pydantic models: ChatMessage, AgentStreamEvent, JobStatus
│       ├── routers/
│       │   ├── agent.py            # POST /agent/chat (SSE stream), GET /agent/tools
│       │   ├── files.py            # POST /files/upload, GET /files, DELETE /files/{name}
│       │   └── jobs.py             # GET /jobs, GET /jobs/{id}
│       └── services/
│           ├── agent.py            # TelecouplingAgent — the ReAct loop (Purdue + Gemini)
│           ├── classifier.py       # Intent classifier: analysis / geospatial / followup
│           ├── mcp_client.py       # Starts MCP subprocesses, routes tool calls
│           └── job_store.py        # In-memory job history
│
├── mcp-servers/
│   ├── invest-mcp/
│   │   ├── server.py               # 16 MCP tools: 13 InVEST models + discovery
│   │   └── utils.py                # run_invest_model(), raster stats, workspace helpers
│   └── qgis-mcp/
│       ├── server.py               # 15 MCP tools: reproject, clip, buffer, render, etc.
│       ├── utils.py                # headless QGIS init, processing helpers
│       └── run_qgis_mcp.sh         # Launch script (must use system Python for PyQGIS)
│
├── frontend/                       # React + TypeScript + Vite + Tailwind
│   └── src/
│       ├── App.tsx                 # Root layout: Sidebar + ChatPanel
│       ├── api.ts                  # fetch wrappers: streamChat, uploadFile, fetchTools, etc.
│       ├── types.ts                # TypeScript interfaces: ChatMessage, AgentStreamEvent, etc.
│       └── components/
│           ├── ChatPanel.tsx       # Main chat UI, file upload, sends to /agent/chat
│           ├── MessageBubble.tsx   # Renders one message (user or assistant)
│           ├── ThinkingIndicator.tsx # Live reasoning display + routing label
│           ├── ToolCallCard.tsx    # Expandable card for each tool call
│           └── Sidebar.tsx         # MCP tools list, job history, system status
│
└── data/
    ├── sample-inputs/              # Pre-packaged InVEST sample data
    │   ├── CarbonStorage/          # Willamette Basin LULC + carbon pools
    │   ├── HabitatQuality/
    │   └── CoastalBlueCarbon/
    ├── outputs/                    # Model run results written here
    └── uploads/                    # User-uploaded files (.tif, .csv, .shp, etc.)
```

---

## 4. Complete End-to-End Example Run

This section walks through every single thing that happens for one real request —
from the user pressing Enter to the final answer appearing in the browser.
No codebase reading required.

---

### 4.1 The Chat

```
User:  "Run Carbon Storage model and interpret the results in a telecoupling context"
```

This is the first message in the conversation (no prior assistant replies).

---

### 4.2 Frontend → Backend  (`ChatPanel.tsx`)

`ChatPanel.tsx` calls `streamChat()` from `api.ts`:

```http
POST /agent/chat
Content-Type: application/json

{
  "messages": [
    { "role": "user", "content": "Run Carbon Storage model and interpret the results in a telecoupling context" }
  ]
}
```

No `job_id` is sent — this is a new conversation.

---

### 4.3 Job Created  (`routers/agent.py`)

```python
job_id = str(uuid.uuid4())
# → "e271cb0b-b475-4e70-8d78-ccdbf7814563"

job_store.create_job(request.messages, job_id=job_id)
# Job written to in-memory store with status = "pending"
```

FastAPI immediately returns a `StreamingResponse` with these headers:

```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
X-Job-ID: e271cb0b-b475-4e70-8d78-ccdbf7814563
```

The HTTP connection stays open. Everything from here is streamed as SSE lines.

---

### 4.4 Intent Classification  (`services/classifier.py`)

The agent calls `classify_intent_llm()` before touching the main ReAct loop.
It sends this single-shot prompt to the LLM:

```
Classify the user message below into exactly one category.
Reply with only the single category word — no punctuation, no explanation.

Categories:
  analysis   — user wants to run, calculate, or compute a NatCap InVEST environmental
               model (carbon storage, habitat quality, water yield, pollination, etc.)
  geospatial — user wants a QGIS spatial operation: reproject, clip, buffer, overlay,
               zonal statistics, raster calculation, render a map, or any vector/raster
               processing
  followup   — user is asking a clarifying or interpretive question about results already
               shown earlier in the conversation (explain, why, what does this mean, etc.)

Prior conversation exists: False
User message: "Run Carbon Storage model and interpret the results in a telecoupling context"

Category:
```

Parameters: `max_tokens=5`, `temperature=0`

**LLM responds:** `analysis`

`_parse_label("analysis")` checks it is in `{"analysis", "geospatial", "followup"}` → valid.

**SSE event emitted to browser:**
```
data: {"type":"classified","data":{"intent":"analysis","label":"InVEST Analysis"}}
```

ThinkingIndicator in the browser shows: `Routing: InVEST Analysis` (green).

---

### 4.5 System Prompt Assembly  (`services/agent.py`)

Three layers are concatenated into one string before the first LLM call.

**Layer 1 — Base prompt (static):**
```
You are an expert environmental analyst assistant for the Telecoupling Toolbox.

You help researchers run NatCap InVEST environmental models and QGIS geospatial
operations to study telecoupling — socioeconomic and environmental interactions
between distant places.

Available InVEST models: habitat quality, carbon storage, water yield, pollination,
sediment delivery, nutrient delivery, coastal blue carbon, crop production, forest
carbon, habitat risk, and recreation.

Guidelines:
1. Before running ANY model, call get_sample_args("<model_name>") to get the exact
   parameter names and file paths. Use the returned "arguments" dict directly in
   your tool call. NEVER invent or guess file paths.
2. Call the tool with EXACTLY the parameter names shown in the arguments dict.
3. Always interpret results in the ecological / telecoupling context.
4. When chaining operations, plan the steps before executing.
5. Report output file paths so users know where results were saved.
6. Be concise but scientifically precise.
```

**Layer 2 — Intent hint:**
Intent is `"analysis"` → `INTENT_HINT["analysis"] = ""`
Nothing appended. The default behaviour (full ReAct, all tools) is correct.

**Layer 3 — Tool catalogue (auto-generated from connected MCP servers):**
```
## Available Tools
  list_models: List all 13 available InVEST models with descriptions.
  list_sample_data: List all available sample input data files grouped by model.
  get_sample_args: Return a ready-to-use argument dict for a specific model.
  run_carbon_storage: Run the InVEST Carbon Storage and Sequestration model.
  run_habitat_quality: Assess habitat quality and degradation across a landscape.
  run_coastal_blue_carbon: Run the Coastal Blue Carbon model.
  run_water_yield: Run the InVEST Annual Water Yield model.
  run_pollination: Run the InVEST Crop Pollination model.
  run_sdr: Run the Sediment Delivery Ratio model.
  run_ndr: Run the Nutrient Delivery Ratio model.
  run_seasonal_water_yield: Run the Seasonal Water Yield model.
  run_forest_carbon: Run the Forest Carbon Edge Effect model.
  run_crop_production_percentile: Run Crop Production (Percentile) model.
  run_crop_production_regression: Run Crop Production (Regression) model.
  run_pollination: Run the InVEST Pollination model.
  run_hra: Run the Habitat Risk Assessment model.
  run_recreation: Run the Recreation Visitation Rate model.
  list_operations: List all available QGIS geospatial operations.
  get_raster_info: Get metadata and band statistics for a raster file.
  get_vector_info: Get metadata and field schema for a vector file.
  reproject_raster: Reproject a raster to a different CRS (e.g. EPSG:4326).
  reproject_vector: Reproject a vector layer to a different CRS.
  clip_raster_by_mask: Clip a raster using a vector polygon mask layer.
  clip_vector_by_extent: Clip vector features to a bounding extent.
  buffer_vector: Create buffer zones around vector features.
  vector_overlay: Perform overlay: intersect, union, difference.
  zonal_statistics: Calculate raster statistics within polygon zones.
  raster_calculator: Perform band math on rasters (GDAL calc).
  render_map: Render a styled map image from layers.
  execute_processing: Run ANY QGIS Processing algorithm by ID.

## How to call a tool
When you need to invoke a tool, output a fenced block like this:

```tool_call
{"name": "tool_name", "arguments": {"param": "value"}}
```

After receiving the tool result, continue your reasoning. When you have a complete
answer, write it as plain text with NO tool_call block.
Never call the same tool with the same arguments twice.
```

---

### 4.6 ReAct Loop — Iteration 1

**SSE event emitted:**
```
data: {"type":"thinking","data":{"iteration":1}}
```

The full messages array sent to the LLM:

```
[
  { "role": "system",  "content": "<assembled system prompt above>" },
  { "role": "user",    "content": "Run Carbon Storage model and interpret the results in a telecoupling context" }
]
```

**How the LLM decides which tool to call:**
The system prompt Guideline 1 says: *"Before running ANY model, call get_sample_args() to get exact parameter names and file paths. NEVER guess file paths."*
The LLM knows it wants `run_carbon_storage` but also knows it must discover the correct argument names first — so it picks `get_sample_args` as the first action.

**LLM raw text response:**
```
I'll start by getting the sample arguments for the Carbon Storage model to find
the exact parameter names and file paths.

```tool_call
{"name": "get_sample_args", "arguments": {"model_name": "carbon_storage"}}
```
```

**`_parse_react_tool_calls()` extracts:**
```python
[{"name": "get_sample_args", "arguments": {"model_name": "carbon_storage"}}]
```

**SSE event emitted:**
```
data: {"type":"tool_call","data":{"tool":"get_sample_args","arguments":{"model_name":"carbon_storage"}}}
```

**`MCPClient.call_tool()` routes the call:**
```
tool name "get_sample_args" → registered to "invest-mcp" server (port 54320)
```
The client sends the call over SSE to the invest-mcp subprocess.

**invest-mcp `server.py` executes:**
```python
@mcp.tool()
def get_sample_args(model_name: str) -> str:
    # Looks up pre-built template for "carbon_storage"
    # Returns exact absolute paths from sample-inputs/ directory
```

**Tool result returned (18.5 ms):**
```json
{
  "model": "carbon_storage",
  "tool_to_call": "run_carbon_storage",
  "arguments": {
    "lulc_cur_path": "/home/shubh/projects/telecoupling-toolbox/telecoupling-app/data/sample-inputs/CarbonStorage/lulc_current_willamette.tif",
    "carbon_pools_path": "/home/shubh/projects/telecoupling-toolbox/telecoupling-app/data/sample-inputs/CarbonStorage/carbon_pools_willamette.csv"
  },
  "note": "Pass these arguments directly to the tool. Add workspace_dir if desired."
}
```

**SSE event emitted:**
```
data: {"type":"tool_result","data":{"tool":"get_sample_args","success":true,"preview":"{\"model\": \"carbon_storage\"...","duration_ms":18.5}}
```

**Result appended to history as a user message:**
```
[
  { "role": "system",    "content": "<system prompt>" },
  { "role": "user",      "content": "Run Carbon Storage model..." },
  { "role": "assistant", "content": "I'll start by getting the sample arguments...\n```tool_call\n..." },
  { "role": "user",      "content": "**Result of `get_sample_args`:**\n```\n{...json...}\n```" }
]
```

---

### 4.7 ReAct Loop — Iteration 2

**SSE event emitted:**
```
data: {"type":"thinking","data":{"iteration":2}}
```

The LLM now has the real file paths in its context.

**How the LLM decides which tool to call:**
The result from `get_sample_args` explicitly states `"tool_to_call": "run_carbon_storage"` and provides a ready-made `arguments` dict. The LLM copies those arguments directly — it does not invent or modify them.

**LLM raw text response:**
```
I have the exact file paths. Now I'll run the Carbon Storage model.

```tool_call
{
  "name": "run_carbon_storage",
  "arguments": {
    "lulc_cur_path": "/home/shubh/projects/telecoupling-toolbox/telecoupling-app/data/sample-inputs/CarbonStorage/lulc_current_willamette.tif",
    "carbon_pools_path": "/home/shubh/projects/telecoupling-toolbox/telecoupling-app/data/sample-inputs/CarbonStorage/carbon_pools_willamette.csv"
  }
}
```
```

**SSE event emitted:**
```
data: {"type":"tool_call","data":{"tool":"run_carbon_storage","arguments":{...}}}
```

**`MCPClient.call_tool()` routes the call:**
```
tool name "run_carbon_storage" → registered to "invest-mcp" server (port 54320)
```

**invest-mcp `server.py` executes:**
```python
@mcp.tool()
def run_carbon_storage(lulc_cur_path: str, carbon_pools_path: str, workspace_dir: str = "") -> str:
    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "carbon_storage"))
    args = {
        "lulc_bas_path": lulc_cur_path,    # InVEST internal name is "bas" not "cur"
        "carbon_pools_path": carbon_pools_path,
        "workspace_dir": ws,
    }
    return run_invest_model("carbon", args, ws)
    # → natcap.invest.carbon.execute(args)
```

InVEST internally:
1. Reads the LULC raster (1049 × 1698 pixels, Willamette Basin, Oregon)
2. Joins each pixel's land-cover code to carbon pool values from the CSV
3. Reclassifies the raster for 4 carbon pools: above-ground, below-ground, soil, dead matter
4. Sums the four pools into total carbon storage per pixel
5. Writes output rasters to `data/outputs/carbon_storage/`

**Tool result returned (3,832 ms — real raster computation):**
```json
{
  "status": "success",
  "model": "Carbon Storage & Sequestration",
  "workspace_dir": "/home/shubh/.../data/outputs/carbon_storage",
  "elapsed_seconds": 3.83,
  "output_files": [
    "c_storage_bas.tif",
    "intermediate_outputs/c_above_bas.tif",
    "intermediate_outputs/c_below_bas.tif",
    "intermediate_outputs/c_dead_bas.tif",
    "intermediate_outputs/c_soil_bas.tif"
  ],
  "raster_summaries": {
    "c_storage_bas.tif":                    {"min":0.0, "max":303.0, "mean":115.39, "stddev":72.96},
    "intermediate_outputs/c_above_bas.tif": {"min":0.0, "max":95.0,  "mean":26.99,  "stddev":25.85},
    "intermediate_outputs/c_below_bas.tif": {"min":0.0, "max":38.0,  "mean":10.76,  "stddev":10.34},
    "intermediate_outputs/c_soil_bas.tif":  {"min":0.0, "max":140.0, "mean":70.27,  "stddev":30.06},
    "intermediate_outputs/c_dead_bas.tif":  {"min":0.0, "max":30.0,  "mean":7.38,   "stddev":8.03}
  }
}
```

**SSE event emitted:**
```
data: {"type":"tool_result","data":{"tool":"run_carbon_storage","success":true,"preview":"{\"status\": \"success\"...","duration_ms":3832.5}}
```

**Result appended to history:**
```
[
  { "role": "system",    "content": "<system prompt>" },
  { "role": "user",      "content": "Run Carbon Storage model..." },
  { "role": "assistant", "content": "I'll start by getting sample arguments...\n```tool_call..." },
  { "role": "user",      "content": "**Result of `get_sample_args`:**\n```\n{...}\n```" },
  { "role": "assistant", "content": "I have the exact file paths. Now I'll run...\n```tool_call..." },
  { "role": "user",      "content": "**Result of `run_carbon_storage`:**\n```\n{...}\n```" }
]
```

---

### 4.8 ReAct Loop — Iteration 3 (Final Answer)

**SSE event emitted:**
```
data: {"type":"thinking","data":{"iteration":3}}
```

The LLM now has real raster statistics in context.

**How the LLM decides to stop calling tools:**
The raster summaries give it concrete numbers. The system prompt says "when you have a complete answer, write it as plain text with NO tool_call block." There is nothing left to discover — no more tools needed.

**LLM raw text response (no `tool_call` block → loop ends):**
```
The Carbon Storage model completed successfully for the Willamette Basin, Oregon.

**Results Summary**

| Carbon Pool   | Mean (t/ha) | Max (t/ha) | Share of Total |
|---------------|-------------|------------|----------------|
| Soil          | 70.27       | 140.0      | 61%            |
| Aboveground   | 26.99       | 95.0       | 23%            |
| Belowground   | 10.76       | 38.0       | 9%             |
| Dead matter   | 7.38        | 30.0       | 6%             |
| **Total**     | **115.39**  | **303.0**  | 100%           |

**Telecoupling Interpretation**

Soil carbon dominates at 61%, characteristic of Pacific Northwest temperate forests.
The high variability (σ = 73 t/ha) reflects a mixed landscape: old-growth forest,
agriculture, and urban areas.

In a telecoupling context:
- International timber markets (distant sending systems) drive logging decisions here,
  reducing aboveground stocks from ~95 t/ha (old-growth) to ~10 t/ha (cleared land).
- Agricultural expansion driven by distant food consumers threatens soil carbon stocks.
- This region acts as a net carbon sink; land-use changes here have global climate
  implications that extend far beyond the Willamette Basin.

Output files saved to: .../data/outputs/carbon_storage/
```

`_parse_react_tool_calls()` finds **no** `tool_call` block → loop exits.

**SSE event emitted:**
```
data: {"type":"response","data":{
  "text": "The Carbon Storage model completed successfully...",
  "tool_calls": [
    {"tool":"get_sample_args",    "success":true, "duration_ms":18.5},
    {"tool":"run_carbon_storage", "success":true, "duration_ms":3832.5}
  ],
  "job_id": "e271cb0b-b475-4e70-8d78-ccdbf7814563"
}}
```

**Job store updated:**
```python
job_store.complete_job("e271cb0b-...", response_text="The Carbon Storage model...")
# status → "completed"
```

**Stream closed:**
```
data: [DONE]
```

---

### 4.9 What the Frontend Does With Each Event

| SSE event type | What the frontend does |
|---|---|
| `classified` | ThinkingIndicator shows `Routing: InVEST Analysis` in green |
| `thinking` (iter 1) | ThinkingIndicator shows `Reasoning (step 1)…` with bounce dots |
| `tool_call` | ThinkingIndicator switches to `Calling get_sample_args…` |
| `tool_result` | Dot animation resumes; ToolCallCard added to the pending list |
| `thinking` (iter 2) | ThinkingIndicator shows `Reasoning (step 2)…` |
| `tool_call` | ThinkingIndicator shows `Calling run_carbon_storage…` |
| `tool_result` | Second ToolCallCard added (shows 3.8 s duration) |
| `thinking` (iter 3) | ThinkingIndicator shows `Reasoning (step 3)…` |
| `response` | Streaming placeholder replaced with final MessageBubble + both ToolCallCards |
| `[DONE]` | SSE reader closed; streaming state cleared |

---

### 4.10 Full Timeline

```
t=0ms     POST /agent/chat received
t=1ms     Job e271cb0b created (status: pending)
t=2ms     StreamingResponse returned, SSE connection open
t=3ms     status → running
t=5ms     [SSE] classified  { intent: "analysis", label: "InVEST Analysis" }
t=180ms   classifier LLM call completes (separate, fast call)
t=185ms   [SSE] thinking    { iteration: 1 }
t=2100ms  Iteration 1 LLM call completes
t=2101ms  [SSE] tool_call   { tool: "get_sample_args", arguments: {...} }
t=2120ms  invest-mcp returns result (18.5 ms)
t=2121ms  [SSE] tool_result { tool: "get_sample_args", success: true, duration_ms: 18.5 }
t=2122ms  [SSE] thinking    { iteration: 2 }
t=4200ms  Iteration 2 LLM call completes
t=4201ms  [SSE] tool_call   { tool: "run_carbon_storage", arguments: {...} }
t=8034ms  invest-mcp returns result (3832.5 ms — real model run)
t=8035ms  [SSE] tool_result { tool: "run_carbon_storage", success: true, duration_ms: 3832.5 }
t=8036ms  [SSE] thinking    { iteration: 3 }
t=10100ms Iteration 3 LLM call completes — no tool_call block found
t=10101ms [SSE] response    { text: "The Carbon Storage model...", tool_calls: [...] }
t=10102ms status → completed
t=10103ms [SSE] [DONE]
t=10104ms SSE connection closed
```

Total wall time: ~10 seconds (dominated by 2 LLM calls + 1 InVEST model run).

---

## 5. The Agent Prompt — What the LLM Actually Receives

Every request assembles a system prompt from three layers stacked together.

### Layer 1 — Base system prompt (static, `agent.py`)

```
You are an expert environmental analyst assistant for the Telecoupling Toolbox.

You help researchers run NatCap InVEST environmental models and QGIS geospatial operations to
study telecoupling — socioeconomic and environmental interactions between distant places.

Available InVEST models: habitat quality, carbon storage, water yield, pollination, sediment
delivery, nutrient delivery, coastal blue carbon, crop production, forest carbon, habitat risk,
and recreation.

Guidelines:
1. Before running ANY model, call get_sample_args("<model_name>") to get the exact parameter
   names and file paths. Use the returned "arguments" dict directly in your tool call.
   NEVER invent or guess file paths — only use paths from get_sample_args or list_sample_data.
2. Call the tool with EXACTLY the parameter names shown in the arguments dict.
3. Always interpret results in the ecological / telecoupling context of the user's question.
4. When chaining operations, plan the steps before executing.
5. Report output file paths so users know where results were saved.
6. Be concise but scientifically precise.
```

Rule 1 is the most important — it exists because without it the LLM guesses file paths, which
causes InVEST to silently skip all raster computation (it just ignores unknown keys).

### Layer 2 — Intent hint (dynamic, injected by `classifier.py`)

Appended only when intent is not `analysis`. Nothing is added for the default case.

**Geospatial intent:**
```
## Routing: Geospatial Operation
The user is requesting a QGIS geospatial operation.
Prefer QGIS tools: reproject_raster, clip_raster_by_mask, buffer_vector,
vector_overlay, zonal_statistics, raster_calculator, render_map, execute_processing.
Call get_raster_info or get_vector_info first if you need layer metadata.
Report the output file path when done.
```

**Follow-up intent:**
```
## Routing: Follow-up Question
This is a follow-up question about results already shown in the conversation.
Answer using the context you already have — do NOT call any tools
unless the user explicitly asks to run something new.
Be concise and scientifically precise.
```

### Layer 3 — Tool catalogue + call format (runtime-generated)

Auto-built from whatever MCP tools are actually connected at startup:

```
## Available Tools
  list_models: List all 13 available InVEST models with descriptions.
  get_sample_args: Return a ready-to-use argument dict for a specific model.
  run_carbon_storage: Run the InVEST Carbon Storage and Sequestration model.
  reproject_raster: Reproject a raster to a different CRS (e.g. EPSG:4326).
  clip_raster_by_mask: Clip a raster using a vector polygon mask layer.
  … (all 31 tools listed)

## How to call a tool
When you need to invoke a tool, output a fenced block like this — nothing else on those lines:

```tool_call
{"name": "tool_name", "arguments": {"param": "value"}}
```

After receiving the tool result, continue your reasoning. When you have a complete answer,
write it as plain text with NO tool_call block.
Never call the same tool with the same arguments twice.
```

This catalogue is regenerated each request so adding a new MCP tool immediately makes it
visible to the LLM — no prompt editing required.

---

## 6. How Tool Calling Works — The Full Mechanics

The LLM **never invokes anything directly**. It outputs text. The agent loop does all the execution.

### Step-by-step for one tool call

**1. LLM outputs raw text containing a fenced block:**
```
I need to discover the exact file paths before running the model.

```tool_call
{"name": "get_sample_args", "arguments": {"model_name": "carbon_storage"}}
```
```

**2. `_parse_react_tool_calls()` extracts it** (`agent.py:99`)

A regex scans the text for ` ```tool_call ... ``` ` blocks, then `json.loads` parses the content:
```python
re.finditer(r'```tool_call\s*([\s\S]*?)```', text, re.IGNORECASE)
# → [{"name": "get_sample_args", "arguments": {"model_name": "carbon_storage"}}]
```

**3. `MCPClient.call_tool()` routes and executes it** (`mcp_client.py`)

Looks up which server owns that tool name, sends the call over SSE to the subprocess, waits for the result:
```python
result_str = await self.mcp_client.call_tool("get_sample_args", {"model_name": "carbon_storage"})
# → '{"model": "carbon_storage", "tool_to_call": "run_carbon_storage", "arguments": {...}}'
```

**4. Result is injected back as a "user" message:**
```python
history.append({
    "role": "user",
    "content": "**Result of `get_sample_args`:**\n```\n{...json...}\n```"
})
```

**5. LLM is called again with the updated history.**
It now knows the real file paths and calls `run_carbon_storage`. The loop continues until the LLM writes a response with no `tool_call` block.

### The ReAct loop visualised

```
┌─────────────────────────────────────────────────────────┐
│  Iteration N                                            │
│                                                         │
│  1. Build messages array:                               │
│       [system prompt] + [chat history] + [tool results] │
│                                                         │
│  2. Call LLM → get text response                        │
│                                                         │
│  3. _parse_react_tool_calls(text)                       │
│       found ```tool_call block?                         │
│         YES → mcp_client.call_tool()                    │
│               append result to history                  │
│               emit SSE: tool_call + tool_result events  │
│               → go to Iteration N+1                     │
│         NO  → emit SSE: response event → DONE          │
└─────────────────────────────────────────────────────────┘
```

**Loop-detection guard:** a `called_keys` set tracks every `tool:args` combination seen.
If the LLM tries to repeat an identical call, the agent injects:
`"You already called that tool. Write your final answer now."` — which breaks the loop.

**Max iterations:** 15 (hardcoded in `agent.py` as `_MAX_ITERATIONS`).

### Why `{{double braces}}` in the prompt template

The prompt is a Python f-string. `{{` and `}}` are escape sequences that render as literal `{` and `}` in the final string the LLM receives — otherwise Python would try to interpret `{"name": ...}` as an f-string substitution and raise a `KeyError`.

---

## 8. The Three Key Services Explained

### `services/classifier.py`
Runs before the LLM. Zero latency, no API call. Reads the latest message and checks:
- InVEST model name + action verb → **analysis** (full ReAct, all tools)
- QGIS operation keyword + action verb → **geospatial** (system prompt emphasises QGIS tools)
- Follow-up phrase or pronoun + prior conversation → **followup** (tells LLM to answer from context, skip tools)

The classified intent is injected as an extra paragraph in the system prompt.

### `services/agent.py`
The ReAct loop. Text-based (not native function calling) so it works reliably on open-weight models.
The LLM outputs a `tool_call` fenced block when it wants to call a tool; the agent parses that, executes it, appends the result as a user message, and loops.
Supports two LLM providers — switch with `LLM_PROVIDER=purdue` or `LLM_PROVIDER=gemini` in `.env`.

### `services/mcp_client.py`
Starts both MCP servers as subprocesses on startup.
Builds a flat map of `tool_name → server`.
Any tool call from the agent is routed transparently — the agent doesn't know or care which server a tool lives on.
If QGIS fails to start (PyQGIS not installed), the backend continues with InVEST-only tools.

---

## 7. Demo Scenarios — What to Show

### Scenario A — InVEST model run (classifier: analysis)
```
"Run Carbon Storage model and interpret the results in a telecoupling context"
```
Watch: routing label, `get_sample_args` call, `run_carbon_storage` (~4s), final interpretation.

### Scenario B — Follow-up question (classifier: followup — no tool calls)
After Scenario A:
```
"Why does soil carbon dominate at 61% here?"
```
Watch: "Follow-up Question" label, LLM answers immediately with no tool calls.

### Scenario C — File upload + analysis
1. Click the paperclip and upload a `.tif` raster
2. Type: "Get metadata for my uploaded raster"
Watch: file path appended to message, `get_raster_info` called with the uploaded path.

### Scenario D — QGIS operation (classifier: geospatial)
```
"Reproject my uploaded raster to EPSG:4326"
```
Watch: "Geospatial Operation" label, `reproject_raster` called, output path returned.

### Scenario E — Discovery
```
"List all available InVEST models"
```
Watch: `list_models` tool call, formatted model list.

---

## 9. API Endpoints Cheatsheet

| Method | Path | What it does |
|--------|------|--------------|
| `GET` | `/health` | Server status, tool count, connected MCP servers |
| `GET` | `/agent/tools` | All MCP tools with descriptions and schemas |
| `POST` | `/agent/chat` | SSE stream — main chat endpoint |
| `POST` | `/agent/chat/sync` | Same but waits for full response (no streaming) |
| `GET` | `/jobs` | Recent job history |
| `GET` | `/jobs/{id}` | Single job details + tool call log |
| `POST` | `/files/upload` | Upload a geospatial file |
| `GET` | `/files` | List uploaded files |
| `DELETE` | `/files/{filename}` | Delete an uploaded file |

Interactive API docs (auto-generated): `http://localhost:8000/docs`

---

## 10. Configuration (`.env`)

```bash
# Which LLM to use
LLM_PROVIDER=purdue          # or "gemini"

# Purdue GenAI Studio (OpenAI-compatible, free institutional)
PURDUE_API_KEY=your-key
PURDUE_MODEL=llama3.3:70b

# Google Gemini (alternative)
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-2.0-flash

# MCP server ports (change if these conflict)
INVEST_MCP_PORT=54320
QGIS_MCP_PORT=54321

# Logging
LOG_LEVEL=INFO
```

---

## 11. Common Questions from the Team

**Q: Why MCP instead of calling InVEST/QGIS directly from the backend?**
MCP decouples tool execution from the agent. Each server has its own Python environment with the right GDAL/PROJ setup. Adding a new InVEST model is one `@mcp.tool()` decorator — no backend changes.

**Q: Why text-based ReAct instead of OpenAI function calling?**
Open-weight models (llama3.3:70b on Purdue) are unreliable with `finish_reason: tool_calls`. Text-based parsing handles both fenced blocks and bare JSON, works on any model.

**Q: Why can't QGIS use the same conda environment as the backend?**
PyQGIS is installed by `apt` (the Linux QGIS package) and compiled against system Python. You can't `pip install pyqgis`. The `run_qgis_mcp.sh` script uses `/usr/bin/python3` which has the bindings. The backend spawns it with `sys.executable` — if that's the conda Python, QGIS tools won't load but InVEST tools still work.

**Q: Where do model outputs go?**
`telecoupling-app/data/outputs/<model_name>/` — e.g. `data/outputs/carbon_storage/c_storage_bas.tif`.

**Q: How does file upload connect to the agent?**
File paths are appended to the user message text as a list. The LLM reads the paths and passes them as arguments to tool calls like `get_raster_info` or `run_habitat_quality`.

**Q: How is conversation context maintained?**
The full message history is sent with every request. The agent includes all prior turns in the LLM context window. The `followup` intent specifically tells the LLM to draw on prior results without calling new tools.

---

## 12. Files Worth Reading First

If you have 30 minutes before the demo, read these in order:

1. `backend/app/services/agent.py` — the core ReAct loop (~250 lines)
2. `backend/app/services/classifier.py` — intent routing (~120 lines)
3. `mcp-servers/invest-mcp/server.py` — how InVEST tools are exposed (~top 80 lines)
4. `frontend/src/components/ChatPanel.tsx` — the full frontend chat logic
5. `AGENTIC_WORKFLOW.md` — end-to-end trace of a real Carbon Storage run
