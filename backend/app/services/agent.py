"""
Telecoupling AI - Agent Loop

ReAct-style (Reason + Act) loop supporting two LLM providers:
  • Purdue GenAI Studio  — text-based ReAct (reliable across open-weight models)
  • Google Gemini        — native function calling via google-genai SDK

Provider selected via LLM_PROVIDER in .env ("purdue" | "gemini").
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, AsyncGenerator

from mcp.types import Tool as MCPTool

from app.core.config import settings
from app.models.agent import AgentStreamEvent, ChatMessage, ToolCallRecord
from app.services.classifier import (
    classify_intent,
    classify_intent_llm,
    classify_intent_gemini,
    INTENT_HINT,
    INTENT_LABEL,
)
from app.services.mcp_client import MCPClient

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = 15

_SYSTEM_PROMPT = """You are an expert environmental analyst assistant for the Telecoupling Toolbox.

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
   For example, run_carbon_storage requires: lulc_cur_path, carbon_pools_path.
3. Always interpret results in the ecological / telecoupling context of the user's question.
4. When chaining operations, plan the steps before executing.
5. Report output file paths so users know where results were saved.
6. Be concise but scientifically precise.
7. ONLY do what the user explicitly asked. Do NOT call extra tools or extra variations of
   the same tool unless the user specifically requested them. One task = one tool call.
   Do NOT attempt sequestration, future scenarios, or additional analysis unless asked.
8. NEVER invent or guess file paths. Only use paths returned by get_sample_args or
   list_sample_data. If a file path is not in those results, it does not exist — do not use it.
9. zonal_statistics requires input_zones to be a VECTOR file (.shp/.gpkg/.geojson).
   NEVER pass a raster (.tif) as input_zones.
"""


# ---------------------------------------------------------------------------
# Schema helpers  (OpenAI function format, also used for tool catalogue)
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "string": "string", "number": "number", "integer": "integer",
    "boolean": "boolean", "array": "array", "object": "object",
}


def _convert_prop(schema: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "type" in schema:
        out["type"] = _TYPE_MAP.get(schema["type"], "string")
    if "description" in schema:
        out["description"] = schema["description"]
    if "enum" in schema:
        out["enum"] = schema["enum"]
    if schema.get("type") == "array" and "items" in schema:
        out["items"] = _convert_prop(schema["items"])
    if schema.get("type") == "object" and "properties" in schema:
        out["properties"] = {k: _convert_prop(v) for k, v in schema["properties"].items()}
    return out


def _mcp_to_openai_tool(tool: MCPTool) -> dict[str, Any]:
    schema = tool.inputSchema or {}
    props  = schema.get("properties", {})
    req    = schema.get("required", [])
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    if props:
        parameters["properties"] = {k: _convert_prop(v) for k, v in props.items()}
    if req:
        parameters["required"] = req
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": (tool.description or "")[:1000],
            "parameters": parameters,
        },
    }


# ---------------------------------------------------------------------------
# ReAct text-call parser
# ---------------------------------------------------------------------------

def _parse_react_tool_calls(text: str) -> list[dict[str, Any]]:
    """
    Extract tool calls from assistant text.  Handles two formats:

    Format 1 — fenced block (preferred):
        ```tool_call
        {"name": "...", "arguments": {...}}
        ```

    Format 2 — bare JSON that looks like a function call:
        {"name": "...", "arguments": {...}}
        {"type": "function", "name": "...", "parameters": {...}}
    """
    calls: list[dict[str, Any]] = []

    # --- Format 1: fenced ```tool_call[s] ... ``` blocks ---
    for m in re.finditer(r'```tool_calls?\s*([\s\S]*?)```', text, re.IGNORECASE):
        try:
            obj = json.loads(m.group(1).strip())
            name = obj.get("name")
            if name:
                calls.append({
                    "name": name,
                    "arguments": obj.get("arguments") or obj.get("parameters") or {},
                })
        except Exception:
            pass

    if calls:
        return calls

    # --- Format 2: try the whole text as JSON ---
    stripped = text.strip()
    try:
        obj = json.loads(stripped)
        items = obj if isinstance(obj, list) else [obj]
        for item in items:
            name = item.get("name") or item.get("function", {}).get("name")
            if name:
                args = (
                    item.get("arguments")
                    or item.get("parameters")
                    or item.get("function", {}).get("arguments")
                    or {}
                )
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                calls.append({"name": name, "arguments": args or {}})
        if calls:
            return calls
    except Exception:
        pass

    return []


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class TelecouplingAgent:
    """LLM-powered agent that drives InVEST / QGIS tools via MCP."""

    def __init__(self, mcp_client: MCPClient) -> None:
        self.mcp_client = mcp_client
        self._openai_tools: list[dict] | None = None

    def _get_tools(self) -> list[dict]:
        if self._openai_tools is None:
            self._openai_tools = [_mcp_to_openai_tool(t) for t in self.mcp_client.list_tools()]
        return self._openai_tools

    def invalidate_tool_cache(self) -> None:
        self._openai_tools = None

    # ------------------------------------------------------------------
    async def run(
        self,
        messages: list[ChatMessage],
        job_id: str,
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        if settings.llm_provider == "purdue":
            async for event in self._run_purdue(messages, job_id):
                yield event
        elif settings.llm_provider == "gemini":
            async for event in self._run_gemini(messages, job_id):
                yield event
        else:
            yield AgentStreamEvent(
                type="error",
                data={"message": f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use 'purdue' or 'gemini'."},
            )

    # ------------------------------------------------------------------
    # Purdue GenAI Studio — text-based ReAct loop
    # ------------------------------------------------------------------

    async def _run_purdue(
        self,
        messages: list[ChatMessage],
        job_id: str,
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        if not settings.purdue_api_key or settings.purdue_api_key == "your-purdue-api-key-here":
            yield AgentStreamEvent(
                type="error",
                data={"message": "PURDUE_API_KEY not set. Add it to .env and restart."},
            )
            return

        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.purdue_api_key,
            base_url=settings.purdue_base_url,
        )

        # Classify intent with LLM (falls back to heuristic on failure)
        intent = await classify_intent_llm(messages, client, settings.purdue_model)
        yield AgentStreamEvent(
            type="classified",
            data={"intent": intent, "label": INTENT_LABEL[intent]},
        )

        # Build tool catalogue for the system prompt — include parameter signatures
        # so the LLM uses the exact argument names each tool expects.
        def _tool_signature(t: dict) -> str:
            name = t["function"]["name"]
            desc = t["function"]["description"].splitlines()[0]
            props = t["function"].get("parameters", {}).get("properties", {})
            required = set(t["function"].get("parameters", {}).get("required", []))
            parts = []
            for pname, pschema in props.items():
                ptype = pschema.get("type", "string")
                if pname in required:
                    parts.append(f"{pname}: {ptype}")
                else:
                    default = '""' if ptype == "string" else ("0" if ptype in ("integer","number") else "false")
                    parts.append(f"{pname}: {ptype} = {default}")
            sig = f"({', '.join(parts)})" if parts else "()"
            return f"  {name}{sig}\n    {desc}"

        tool_lines = "\n".join(_tool_signature(t) for t in self._get_tools())
        react_system = f"""{_SYSTEM_PROMPT}{INTENT_HINT[intent]}

## Available Tools
{tool_lines}

## How to call a tool
When you need to invoke a tool, output a fenced block like this — nothing else on those lines:

```tool_call
{{"name": "tool_name", "arguments": {{"param": "value"}}}}
```

After receiving the tool result, continue your reasoning. When you have a complete answer,
write it as plain text with NO tool_call block.
Never call the same tool with the same arguments twice.
"""

        history: list[dict] = [{"role": "system", "content": react_system}]
        for m in messages:
            role = "assistant" if m.role == "model" else m.role
            history.append({"role": role, "content": m.content})

        tool_calls_log: list[ToolCallRecord] = []
        called_keys: set[str] = set()

        for iteration in range(_MAX_ITERATIONS):
            yield AgentStreamEvent(type="thinking", data={"iteration": iteration + 1})

            try:
                response = await client.chat.completions.create(
                    model=settings.purdue_model,
                    messages=history,
                )
            except Exception as exc:
                logger.exception("Purdue API error on iteration %d", iteration + 1)
                yield AgentStreamEvent(type="error", data={"message": str(exc)})
                return

            assistant_text = response.choices[0].message.content or ""
            history.append({"role": "assistant", "content": assistant_text})

            calls = _parse_react_tool_calls(assistant_text)

            if not calls:
                # No tool call → final answer
                yield AgentStreamEvent(
                    type="response",
                    data={
                        "text": assistant_text,
                        "tool_calls": [tc.model_dump() for tc in tool_calls_log],
                        "job_id": job_id,
                    },
                )
                return

            # Execute tool calls; collect results to feed back in one user turn
            results_block = ""
            for call in calls:
                tool_name = call["name"]
                arguments = call.get("arguments", {})

                call_key = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
                if call_key in called_keys:
                    logger.warning("Loop: %s called again — requesting final answer", tool_name)
                    history.append({
                        "role": "user",
                        "content": "You already called that tool. Using the results you have, write your final answer as plain text now.",
                    })
                    break
                called_keys.add(call_key)

                yield AgentStreamEvent(
                    type="tool_call",
                    data={"tool": tool_name, "arguments": arguments},
                )

                t0 = time.monotonic()
                try:
                    result_str = await self.mcp_client.call_tool(tool_name, arguments)
                    success, error_msg = True, None
                except Exception as exc:
                    result_str = f"Tool error: {exc}"
                    success, error_msg = False, str(exc)
                    logger.warning("Tool %s failed: %s", tool_name, exc)

                duration_ms = round((time.monotonic() - t0) * 1000, 1)
                tool_calls_log.append(ToolCallRecord(
                    tool=tool_name, arguments=arguments, result=result_str,
                    success=success, error=error_msg, duration_ms=duration_ms,
                ))

                preview = result_str[:600] + ("…" if len(result_str) > 600 else "")
                yield AgentStreamEvent(
                    type="tool_result",
                    data={"tool": tool_name, "success": success,
                          "preview": preview, "duration_ms": duration_ms},
                )

                results_block += f"\n**Result of `{tool_name}`:**\n```\n{result_str[:3000]}\n```\n"

            # Feed tool results back as a user message
            if results_block:
                history.append({"role": "user", "content": results_block.strip()})

        yield AgentStreamEvent(
            type="error",
            data={"message": f"Agent stopped after {_MAX_ITERATIONS} iterations."},
        )

    # ------------------------------------------------------------------
    # Google Gemini — native function calling
    # ------------------------------------------------------------------

    async def _run_gemini(
        self,
        messages: list[ChatMessage],
        job_id: str,
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        if not settings.gemini_api_key:
            yield AgentStreamEvent(
                type="error",
                data={"message": "GEMINI_API_KEY not set. Update .env and restart."},
            )
            return

        from google import genai
        from google.genai import types as gtypes

        def _to_schema(schema: dict) -> gtypes.Schema:
            props = schema.get("properties", {})
            req   = schema.get("required", [])
            return gtypes.Schema(
                type="OBJECT",
                properties={k: gtypes.Schema(**_convert_prop(v)) for k, v in props.items()} if props else None,
                required=req or None,
            )

        # Create client early so the classifier can reuse it
        client = genai.Client(api_key=settings.gemini_api_key)

        # Classify intent with LLM (falls back to heuristic on failure)
        intent = await classify_intent_gemini(messages, client, settings.gemini_model)
        yield AgentStreamEvent(
            type="classified",
            data={"intent": intent, "label": INTENT_LABEL[intent]},
        )

        declarations = [
            gtypes.FunctionDeclaration(
                name=t.name,
                description=(t.description or "")[:1000],
                parameters=_to_schema(t.inputSchema or {}) if (t.inputSchema or {}).get("properties") else None,
            )
            for t in self.mcp_client.list_tools()
        ]

        history = [
            gtypes.Content(role=m.role, parts=[gtypes.Part(text=m.content)])
            for m in messages[:-1]
        ]
        system_instruction = _SYSTEM_PROMPT + INTENT_HINT[intent]
        chat = client.aio.chats.create(
            model=settings.gemini_model,
            config=gtypes.GenerateContentConfig(
                tools=[gtypes.Tool(function_declarations=declarations)],
                system_instruction=system_instruction,
            ),
            history=history,
        )

        current_input: Any = messages[-1].content
        tool_calls_log: list[ToolCallRecord] = []

        for iteration in range(_MAX_ITERATIONS):
            yield AgentStreamEvent(type="thinking", data={"iteration": iteration + 1})
            try:
                response = await chat.send_message(current_input)
            except Exception as exc:
                logger.exception("Gemini error on iteration %d", iteration + 1)
                yield AgentStreamEvent(type="error", data={"message": str(exc)})
                return

            function_calls = response.function_calls or []
            if not function_calls:
                yield AgentStreamEvent(
                    type="response",
                    data={
                        "text": _extract_gemini_text(response),
                        "tool_calls": [tc.model_dump() for tc in tool_calls_log],
                        "job_id": job_id,
                    },
                )
                return

            response_parts: list[Any] = []
            for fc in function_calls:
                tool_name = fc.name
                arguments = dict(fc.args) if fc.args else {}
                yield AgentStreamEvent(type="tool_call", data={"tool": tool_name, "arguments": arguments})

                t0 = time.monotonic()
                try:
                    result_str = await self.mcp_client.call_tool(tool_name, arguments)
                    success, error_msg = True, None
                except Exception as exc:
                    result_str, success, error_msg = f"Tool error: {exc}", False, str(exc)

                duration_ms = round((time.monotonic() - t0) * 1000, 1)
                tool_calls_log.append(ToolCallRecord(
                    tool=tool_name, arguments=arguments, result=result_str,
                    success=success, error=error_msg, duration_ms=duration_ms,
                ))
                preview = result_str[:600] + ("…" if len(result_str) > 600 else "")
                yield AgentStreamEvent(
                    type="tool_result",
                    data={"tool": tool_name, "success": success,
                          "preview": preview, "duration_ms": duration_ms},
                )
                response_parts.append(
                    gtypes.Part.from_function_response(name=tool_name, response={"result": result_str})
                )
            current_input = response_parts

        yield AgentStreamEvent(
            type="error",
            data={"message": f"Agent stopped after {_MAX_ITERATIONS} iterations."},
        )


def _extract_gemini_text(response: Any) -> str:
    try:
        return response.text
    except Exception:
        parts = [p.text for p in (response.parts or []) if hasattr(p, "text") and p.text]
        return "\n".join(parts) or "[No text in response]"
