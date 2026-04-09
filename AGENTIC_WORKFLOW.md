# Telecoupling AI — Agentic Workflow Documentation

> **Audience:** Research collaborators and developers joining the Telecoupling Toolbox project.
> This document walks through a real end-to-end agent run, explaining every component,
> decision, and tool invocation involved.

---

## 1. System Architecture Overview

```
User (Browser)
    │
    │  HTTP / SSE
    ▼
┌─────────────────────────────────────────────┐
│  React Frontend  (Vite + Tailwind)          │
│  • ChatPanel — sends messages, streams SSE  │
│  • Sidebar   — shows tools, jobs, status    │
│  • ThinkingIndicator — live ReAct progress  │
└────────────────────┬────────────────────────┘
                     │  POST /agent/chat  (SSE stream)
                     ▼
┌─────────────────────────────────────────────┐
│  FastAPI Backend  (:8000)                   │
│  • /agent/chat   → TelecouplingAgent.run()  │
│  • /agent/tools  → list MCP tools           │
│  • /jobs         → job history              │
│  • /health       → server status            │
└────────────────────┬────────────────────────┘
                     │  ReAct Loop (text-based)
                     ▼
┌─────────────────────────────────────────────┐
│  LLM: llama3.3:70b via Purdue GenAI Studio  │
│  (OpenAI-compatible API, free institutional)│
└────────────────────┬────────────────────────┘
                     │  MCP tool calls
                     ▼
┌─────────────────────────────────────────────┐
│  MCP Client (SSE transport)                 │
│  Manages long-lived ClientSessions          │
└────────────────────┬────────────────────────┘
                     │  SSE subprocess
                     ▼
┌─────────────────────────────────────────────┐
│  invest-mcp Server  (:54320)                │
│  16 tools: 13 InVEST models +               │
│  list_models + list_sample_data +           │
│  get_sample_args                            │
└────────────────────┬────────────────────────┘
                     │  natcap.invest Python API
                     ▼
              InVEST Model Execution
              (raster output → workspace/)
```

---

## 2. Agents Involved

| Agent | Role | Implementation |
|---|---|---|
| **TelecouplingAgent** | Orchestrates the full ReAct loop — builds prompts, parses tool calls, feeds results back | `backend/app/services/agent.py` |
| **MCPClient** | Manages subprocess lifecycle + SSE sessions for MCP servers | `backend/app/services/mcp_client.py` |
| **invest-mcp Server** | Exposes all 13 InVEST models + discovery tools as callable MCP tools | `mcp-servers/invest-mcp/server.py` |
| **LLM (llama3.3:70b)** | Reasons about the task, decides which tools to call, interprets results | Purdue GenAI Studio |

---

## 3. Sample Request

```
User: "Run Carbon Storage model and interpret the results in a telecoupling context"
```

**What the agent needs to do:**
1. Discover sample data paths (it cannot guess file paths)
2. Call the Carbon Storage model with correct InVEST parameter names
3. Parse raster output statistics
4. Interpret the numbers in an environmental telecoupling context

---

## 4. Step-by-Step Agent Execution

### Step 0 — Request Ingestion

**Where:** `POST /agent/chat` → `routers/agent.py`

```python
# A job ID is created and tracked in the in-memory job store
job_id = str(uuid.uuid4())   # e.g. "e271cb0b-b475-4e70-8d78-ccdbf7814563"
job_store.create_job(messages, job_id=job_id)
job_store.set_running(job_id)
```

The endpoint returns a `StreamingResponse` with `media_type="text/event-stream"`.
Every subsequent event is sent as `data: {json}\n\n` — standard Server-Sent Events.

---

### Step 1 — Prompt Assembly

**Where:** `TelecouplingAgent._run_purdue()` → `agent.py`

The agent builds the LLM conversation history. Three layers are combined:

**Layer 1 — System prompt** (injected once):
```
You are an expert environmental analyst assistant for the Telecoupling Toolbox.
...
Guidelines:
1. Before running ANY model, call get_sample_args("<model_name>") to get the exact
   parameter names and file paths. NEVER invent or guess file paths.
2. Call the tool with EXACTLY the parameter names shown in the arguments dict.
...
```

**Layer 2 — Tool catalogue** (auto-generated from MCP tool list):
```
Available Tools:
  list_models: List all 13 available InVEST models with descriptions.
  list_sample_data: List all available sample input data files grouped by model.
  get_sample_args: Return a ready-to-use argument dict for a specific model.
  run_carbon_storage: Run the InVEST Carbon Storage and Sequestration model.
  run_habitat_quality: Assesses habitat quality and degradation...
  ... (16 tools total)
```

**Layer 3 — Tool call format instruction**:
```
When you need to invoke a tool, output a fenced block like this:

```tool_call
{"name": "tool_name", "arguments": {"param": "value"}}
```

After receiving the tool result, continue your reasoning.
When you have a complete answer, write it as plain text with NO tool_call block.
Never call the same tool with the same arguments twice.
```

**Layer 4 — User message**:
```
"Run Carbon Storage model and interpret the results in a telecoupling context"
```

**SSE event emitted:**
```json
{"type": "thinking", "data": {"iteration": 1}}
```

---

### Step 2 — LLM Call #1 (Iteration 1)

**Where:** Purdue GenAI Studio API → `llama3.3:70b`

The LLM reasons:
> *"I need to run the Carbon Storage model. The system prompt says to call
> `get_sample_args` first to get exact file paths. I should not guess paths."*

**LLM output** (raw text containing a fenced tool_call block):
````
I'll start by getting the sample arguments for the Carbon Storage model.

```tool_call
{"name": "get_sample_args", "arguments": {"model_name": "carbon_storage"}}
```
````

**Parser (`_parse_react_tool_calls`)** extracts:
```python
[{"name": "get_sample_args", "arguments": {"model_name": "carbon_storage"}}]
```

**SSE event emitted:**
```json
{"type": "tool_call", "data": {"tool": "get_sample_args", "arguments": {"model_name": "carbon_storage"}}}
```

---

### Step 3 — MCP Tool Execution: `get_sample_args`

**Where:** `MCPClient.call_tool()` → SSE → `invest-mcp` subprocess → `server.py`

The MCP server executes:
```python
@mcp.tool()
def get_sample_args(model_name: str) -> str:
    # Looks up a pre-built template for "carbon_storage"
    # Returns exact absolute paths from the sample-inputs/ directory
```

**Tool result:**
```json
{
  "model": "carbon_storage",
  "tool_to_call": "run_carbon_storage",
  "arguments": {
    "lulc_cur_path": "/home/shubh/.../CarbonStorage/lulc_current_willamette.tif",
    "carbon_pools_path": "/home/shubh/.../CarbonStorage/carbon_pools_willamette.csv"
  },
  "note": "Pass these arguments directly to the tool. Add workspace_dir if desired."
}
```

**Duration:** 18.5ms

**SSE event emitted:**
```json
{
  "type": "tool_result",
  "data": {
    "tool": "get_sample_args",
    "success": true,
    "preview": "{\n  \"model\": \"carbon_storage\"...",
    "duration_ms": 18.5
  }
}
```

The result is appended to the LLM history as a user message:
```
**Result of `get_sample_args`:**
```
{...json result...}
```
```

---

### Step 4 — LLM Call #2 (Iteration 2)

**Where:** Purdue GenAI Studio API → `llama3.3:70b`

The LLM now has the real file paths in context and reasons:
> *"I have the exact paths. The tool to call is `run_carbon_storage` with
> `lulc_cur_path` and `carbon_pools_path`. Let me run it."*

**LLM output:**
````
```tool_call
{
  "name": "run_carbon_storage",
  "arguments": {
    "lulc_cur_path": "/home/shubh/.../CarbonStorage/lulc_current_willamette.tif",
    "carbon_pools_path": "/home/shubh/.../CarbonStorage/carbon_pools_willamette.csv"
  }
}
```
````

**SSE event emitted:**
```json
{"type": "thinking", "data": {"iteration": 2}}
{"type": "tool_call", "data": {"tool": "run_carbon_storage", "arguments": {...}}}
```

---

### Step 5 — MCP Tool Execution: `run_carbon_storage`

**Where:** `MCPClient.call_tool()` → SSE → `invest-mcp` subprocess → `natcap.invest.carbon.execute()`

The MCP server translates the user-facing parameter names to InVEST's internal API:

```python
# Key mapping fix (bug that was discovered and fixed during this session):
args = {
    "lulc_bas_path": lulc_cur_path,      # InVEST uses "bas" not "cur"
    "carbon_pools_path": carbon_pools_path,
    "workspace_dir": ws,
}
# natcap.invest.carbon.execute(args) runs the actual model
```

**What InVEST does internally:**
1. Reads the LULC raster (1049 × 1698 pixels, Willamette Basin, Oregon)
2. Joins each pixel's land cover code to carbon pool values from the CSV
3. Reclassifies the raster for 4 carbon pools: above-ground, below-ground, soil, dead
4. Sums the four pools into total carbon storage
5. Writes output rasters to workspace

**Tool result (abbreviated):**
```json
{
  "status": "success",
  "model": "Carbon Storage & Sequestration",
  "workspace_dir": ".../data/outputs/carbon_storage",
  "elapsed_seconds": 1.28,
  "output_files": [
    "c_storage_bas.tif",
    "intermediate_outputs/c_above_bas.tif",
    "intermediate_outputs/c_below_bas.tif",
    "intermediate_outputs/c_dead_bas.tif",
    "intermediate_outputs/c_soil_bas.tif"
  ],
  "raster_summaries": {
    "c_storage_bas.tif":              {"min": 0.0, "max": 303.0, "mean": 115.39, "stddev": 72.96},
    "intermediate_outputs/c_above_bas.tif": {"min": 0.0, "max": 95.0,  "mean": 26.99, "stddev": 25.85},
    "intermediate_outputs/c_below_bas.tif": {"min": 0.0, "max": 38.0,  "mean": 10.76, "stddev": 10.34},
    "intermediate_outputs/c_soil_bas.tif":  {"min": 0.0, "max": 140.0, "mean": 70.27, "stddev": 30.06},
    "intermediate_outputs/c_dead_bas.tif":  {"min": 0.0, "max": 30.0,  "mean": 7.38,  "stddev": 8.03}
  }
}
```

**Duration:** 3,832.5ms (3.8 seconds — real InVEST raster computation)

**SSE event emitted:**
```json
{
  "type": "tool_result",
  "data": {
    "tool": "run_carbon_storage",
    "success": true,
    "preview": "{\n  \"status\": \"success\"...",
    "duration_ms": 3832.5
  }
}
```

---

### Step 6 — LLM Call #3 (Iteration 3) — Final Answer

**Where:** Purdue GenAI Studio API → `llama3.3:70b`

The LLM now has real raster statistics and reasons:
> *"The model succeeded. I have mean carbon storage of 115.39 t/ha across the
> Willamette Basin. Soil carbon dominates at 70.27 t/ha (61% of total).
> No more tool calls needed — I can write the final interpretation."*

**LLM output (no tool_call block → triggers final response):**
```
The Carbon Storage model has been successfully run...

Mean carbon storage: ~115.4 t/ha, with standard deviation ~72.96 t/ha.
This variability reflects significant differences across land cover types.

In a telecoupling context:
- Global timber demand → local logging → reduced aboveground carbon (27 t/ha mean)
- Agricultural expansion driven by distant consumers threatens soil carbon (70 t/ha)
- This region acts as a net carbon sink; land-use changes here have global climate implications
- Recommend integrating with Habitat Quality model to assess co-impacts on biodiversity

Output files saved to: .../data/outputs/carbon_storage/
```

**SSE event emitted:**
```json
{
  "type": "response",
  "data": {
    "text": "The Carbon Storage model has been successfully run...",
    "tool_calls": [
      {"tool": "get_sample_args",     "success": true,  "duration_ms": 18.5},
      {"tool": "run_carbon_storage",  "success": true,  "duration_ms": 3832.5}
    ],
    "job_id": "e271cb0b-b475-4e70-8d78-ccdbf7814563"
  }
}
```

---

### Step 7 — Stream Termination

**Where:** `routers/agent.py`

```python
job_store.complete_job(job_id, response_text=final_text)
yield "data: [DONE]\n\n"
```

The frontend receives `[DONE]`, closes the SSE reader, and marks the message as complete.

---

## 5. Tool Call Summary

| # | Tool | Arguments | Result | Duration |
|---|---|---|---|---|
| 1 | `get_sample_args` | `{"model_name": "carbon_storage"}` | Exact file paths for lulc + carbon pools | 18.5ms |
| 2 | `run_carbon_storage` | `{"lulc_cur_path": "...", "carbon_pools_path": "..."}` | 5 rasters, mean 115.4 t/ha | 3,832.5ms |

**Total agent iterations:** 3 (2 tool calls + 1 final answer)
**Total wall time:** ~10s (LLM calls + model execution)

---

## 6. ReAct Loop Mechanics

The agent uses a **text-based ReAct (Reason + Act)** loop rather than native function calling.
This was chosen for reliability with open-weight models on Purdue GenAI Studio.

```
┌─────────────────────────────────────────────────────────┐
│                    ReAct Loop                           │
│                                                         │
│  1. Build prompt (system + tool catalogue + history)    │
│  2. Call LLM → get text response                        │
│  3. Parse text for ```tool_call blocks                  │
│       YES → execute tool via MCP                        │
│              append result to history as user message   │
│              loop back to step 1                        │
│       NO  → emit "response" event → DONE               │
└─────────────────────────────────────────────────────────┘
```

**Loop-detection guard:** A `called_keys` set tracks every `tool:args` combination.
If the model tries to call the same tool with the same arguments twice, the agent
injects a "write your final answer now" user message to break the loop.

**Max iterations:** 15 (configurable via `_MAX_ITERATIONS`)

---

## 7. Key Engineering Decisions

### Why text-based ReAct instead of native function calling?
Open-weight models (llama3.3:70b) are non-deterministic about whether they use
`finish_reason: tool_calls` or embed JSON in plain text content. Text-based ReAct
works regardless of output format — the parser handles both fenced blocks and bare JSON.

### Why SSE instead of WebSockets?
SSE is unidirectional (server → client), stateless, and works through standard HTTP
proxies. Each thinking step, tool call, and result is streamed individually so the
user sees progress in real time rather than waiting for the full response.

### Why a `get_sample_args` discovery tool?
Without it, the LLM guesses parameter names and file paths. The wrong names (`lulc_map`
instead of `lulc_cur_path`) caused silent Pydantic validation failures. `get_sample_args`
returns a ready-to-use dict the model can pass directly — eliminating all guesswork.

### Why MCP (Model Context Protocol)?
MCP decouples tool hosting from the agent. The `invest-mcp` server runs as a
separate subprocess with its own conda environment, correct PROJ/GDAL configuration,
and can be updated independently of the backend. New models are added by decorating
a Python function with `@mcp.tool()` — no backend changes required.

---

## 8. Output Files Produced

```
telecoupling-app/data/outputs/carbon_storage/
├── c_storage_bas.tif                    ← MAIN OUTPUT: total carbon (t/ha)
├── report.html                          ← InVEST HTML summary report
├── intermediate_outputs/
│   ├── c_above_bas.tif                  ← aboveground biomass carbon
│   ├── c_below_bas.tif                  ← belowground (root) carbon
│   ├── c_soil_bas.tif                   ← soil organic carbon
│   └── c_dead_bas.tif                   ← dead organic matter carbon
└── taskgraph_cache/
    └── taskgraph.db/taskgraph_data.db   ← InVEST task cache (skip re-runs)
```

---

## 9. Carbon Storage Results — Scientific Interpretation

| Pool | Mean (t/ha) | Max (t/ha) | % of Total |
|---|---|---|---|
| Soil | 70.27 | 140.0 | **61%** |
| Aboveground | 26.99 | 95.0 | 23% |
| Belowground | 10.76 | 38.0 | 9% |
| Dead matter | 7.38 | 30.0 | 6% |
| **Total** | **115.39** | **303.0** | 100% |

**Telecoupling interpretation:**
- Soil carbon dominance (61%) is characteristic of Pacific Northwest temperate forests
- The high variability (σ = 73 t/ha) reflects a mixed landscape: forests, agriculture, urban
- Max of 303 t/ha corresponds to old-growth riparian woodland LULC codes
- In telecoupling terms: international timber markets in distant sending systems
  drive logging decisions in this receiving system, reducing aboveground stocks by
  converting forest pixels (95 t/ha above) to cropland/pasture (5–12 t/ha above)

---

## 10. Debugging Case Study: Silent Parameter Name Bug

**Symptom:** Model ran in 0.03s, `output_files: []`, no rasters written.

**Diagnosis chain:**
1. Checked workspace directory → only `report.html` and taskgraph DB
2. Ran model directly → same result even in fresh workspace
3. Read `natcap.invest.carbon.execute()` source code
4. Discovered InVEST uses `lulc_bas_path` not `lulc_cur_path`
5. The MCP server was passing the wrong key → InVEST silently skipped all raster tasks

**Fix in `server.py`:**
```python
# Before (wrong):
args = {"lulc_cur_path": lulc_cur_path, ...}

# After (correct):
args = {"lulc_bas_path": lulc_cur_path, ...}   # InVEST internal name
```

**Lesson:** Always validate tool parameter names against the underlying library's
API, not intuitive naming conventions. InVEST uses "bas/alt" (baseline/alternate)
rather than "cur/fut" (current/future) for scenario-based models.

---

## 11. Running the Stack

```bash
# 1. Activate conda environment
conda activate telecoupling

# 2. Start backend (spawns invest-mcp automatically)
cd telecoupling-app
python -m uvicorn app.main:app --port 8000 --app-dir backend

# 3. Start frontend (separate terminal)
cd telecoupling-app/frontend
npm run dev

# 4. Open browser
open http://localhost:5173
```

**Health check:**
```bash
curl http://localhost:8000/health
# {"status":"healthy","tool_count":16,"mcp_servers":["invest-mcp"],...}
```

---

*Generated from a live agent session — Telecoupling AI v0.1.0*
