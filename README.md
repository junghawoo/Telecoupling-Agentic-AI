# Telecoupling AI Application

## Project Structure

```
telecoupling-app/
├── mcp-servers/
│   ├── invest-mcp/       # InVEST Model Context Protocol server (13 tools)
│   └── qgis-mcp/         # QGIS geospatial operations MCP server
├── backend/
│   └── app/
│       ├── core/          # Configuration, LLM client, agent loop
│       ├── models/        # Pydantic data models
│       ├── routers/       # FastAPI route handlers
│       └── services/      # Business logic, MCP client integration
├── frontend/              # React + TypeScript + Vite UI
├── data/
│   ├── sample-inputs/     # InVEST sample/test data
│   └── outputs/           # Model run outputs
└── docs/                  # Documentation
```

## Quick Start

### 1. Activate Environment
```bash
conda activate telecoupling
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3. Start MCP Servers
```bash
# Terminal 1: InVEST MCP Server
cd mcp-servers/invest-mcp
python server.py

# Terminal 2: QGIS MCP Server  
cd mcp-servers/qgis-mcp
python server.py
```

### 4. Start Backend
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

### 5. Start Frontend
```bash
cd frontend
npm run dev
```

## Technology Stack

| Component | Technology |
|-----------|-----------|
| LLM | Google Gemini 2.0 Flash |
| Agent Protocol | Model Context Protocol (MCP) |
| Environmental Models | NatCap InVEST 3.14.3 |
| Geospatial Engine | QGIS (headless) |
| Backend | Python FastAPI |
| Frontend | React + TypeScript + Vite |
| Deployment | Docker + Kubernetes (Purdue Geddes HPC) |

## Environment

- **Python**: 3.11 (conda: `telecoupling`)
- **Key packages**: natcap.invest, mcp, google-generativeai, langchain, rasterio, geopandas, fastapi
