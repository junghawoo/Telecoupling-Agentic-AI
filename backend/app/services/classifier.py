"""
Telecoupling AI - Intent Classifier

Classifies the user's latest message into one of three routing intents:

  "analysis"    — Run/calculate a NatCap InVEST environmental model
  "geospatial"  — QGIS spatial operation (reproject, clip, buffer, render, etc.)
  "followup"    — Follow-up question about results already shown in this conversation

The classifier is heuristic (no LLM call) so it adds zero latency and no cost.
It injects an intent-specific hint into the agent's system prompt to steer behaviour.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.models.agent import ChatMessage

logger = logging.getLogger(__name__)

_VALID_INTENTS = {"analysis", "geospatial", "followup"}

_CLASSIFICATION_PROMPT = """\
Classify the user message below into exactly one category. \
Reply with only the single category word — no punctuation, no explanation.

Categories:
  analysis   — user wants to run, calculate, or compute a NatCap InVEST environmental model \
(carbon storage, habitat quality, water yield, pollination, sediment, etc.)
  geospatial — user wants a QGIS spatial operation: reproject, clip, buffer, overlay, \
zonal statistics, raster calculation, render a map, or any other vector/raster processing
  followup   — user is asking a clarifying or interpretive question about results already \
shown earlier in the conversation (explain, why, what does this mean, summarise, etc.)

Prior conversation exists: {has_history}
User message: "{latest}"

Category:"""

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

_INVEST_MODELS = {
    "carbon", "habitat quality", "water yield", "pollination",
    "sediment", "nutrient", "coastal blue carbon", "blue carbon",
    "crop production", "forest carbon", "habitat risk", "recreation",
    "invest", "natcap",
}

_ANALYSIS_VERBS = {
    "run", "execute", "calculate", "compute", "model",
    "analyze", "analyse", "simulate", "perform",
}

# QGIS operations — only match if paired with an action verb
_QGIS_OPS = {
    "reproject", "clip", "buffer", "overlay", "zonal statistics",
    "raster calc", "band math", "render", "visualize", "visualise",
    "intersect", "union", "dissolve", "merge layers",
    "qgis", "qgis tool", "qgis operation", "qgis algorithm",
    "processing algorithm", "list_operations", "list_algorithms",
    "get_raster_info", "get_vector_info", "execute_processing",
}

# File / layer indicators that suggest geospatial work
_SPATIAL_INDICATORS = {
    ".tif", ".tiff", ".shp", ".gpkg", ".geojson",
    "raster", "vector", "shapefile", "geotiff",
    "crs", "epsg", "layer", "extent",
}

# Discovery verbs — listing/showing tools is still a geospatial action
_DISCOVERY_VERBS = {"list", "show", "display", "what", "find", "search", "get"}

# Phrases that open a follow-up question
_FOLLOWUP_PHRASES = {
    "what does", "what do", "why is", "why are", "why did",
    "how does", "how do", "explain", "elaborate", "tell me more",
    "what is the", "what are the", "can you explain",
    "what does this mean", "what does that mean", "what does it mean",
    "interpret", "summarize", "summarise", "in simple terms",
    "break it down", "what's the significance", "what is the significance",
}

# Pronouns that refer back to previous output
_BACK_REF = re.compile(
    r'\b(it|this|that|they|those|these|the result|the output|the model'
    r'|these results|those results|the analysis|the values|the numbers)\b',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_intent(messages: list[ChatMessage]) -> str:
    """
    Inspect the latest user message and return one of:
        "analysis" | "geospatial" | "followup"
    """
    latest = next((m.content for m in reversed(messages) if m.role == "user"), "")
    text = latest.lower().strip()

    prior_assistant_count = sum(1 for m in messages[:-1] if m.role == "model")

    # ------------------------------------------------------------------
    # 1. Geospatial: explicit QGIS operation + action verb / operation word
    # ------------------------------------------------------------------
    has_qgis_op  = any(op in text for op in _QGIS_OPS)
    has_spatial  = any(ind in text for ind in _SPATIAL_INDICATORS)
    has_action   = any(v in text for v in _ANALYSIS_VERBS | _QGIS_OPS)
    has_discover = any(v in text for v in _DISCOVERY_VERBS)

    if has_qgis_op and (has_action or has_discover):
        return "geospatial"

    # File extension present + action verb → geospatial even without explicit op
    if has_spatial and has_action and not any(m in text for m in _INVEST_MODELS):
        return "geospatial"

    # ------------------------------------------------------------------
    # 2. Analysis: InVEST model name + action verb (or first message with model)
    # ------------------------------------------------------------------
    has_model = any(m in text for m in _INVEST_MODELS)
    has_verb  = any(v in text for v in _ANALYSIS_VERBS)

    if has_model and has_verb:
        return "analysis"

    if has_model and prior_assistant_count == 0:
        # First message mentioning a model → analysis even without explicit verb
        return "analysis"

    # ------------------------------------------------------------------
    # 3. Follow-up: question about prior results
    # ------------------------------------------------------------------
    if prior_assistant_count > 0:
        for phrase in _FOLLOWUP_PHRASES:
            if phrase in text or text.startswith(phrase):
                return "followup"

        # Short message with a back-reference pronoun
        if len(text) < 160 and _BACK_REF.search(text):
            return "followup"

    # ------------------------------------------------------------------
    # Default
    # ------------------------------------------------------------------
    return "analysis"


# ---------------------------------------------------------------------------
# LLM-based classifiers (semantic, with heuristic fallback)
# ---------------------------------------------------------------------------


def _build_prompt(messages: list[ChatMessage]) -> str:
    latest = next((m.content for m in reversed(messages) if m.role == "user"), "")
    has_history = any(m.role == "model" for m in messages[:-1])
    return _CLASSIFICATION_PROMPT.format(latest=latest, has_history=has_history)


def _parse_label(raw: str) -> str | None:
    """Extract the first word and return it if it is a valid intent, else None."""
    word = raw.strip().lower().split()[0] if raw.strip() else ""
    return word if word in _VALID_INTENTS else None


async def classify_intent_llm(
    messages: list[ChatMessage],
    openai_client: Any,
    model: str,
) -> str:
    """
    Classify intent using an OpenAI-compatible async client (Purdue GenAI Studio).
    Falls back to the heuristic classifier on any error.

    Uses max_tokens=5 and temperature=0 — fast and deterministic.
    """
    try:
        response = await openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _build_prompt(messages)}],
            max_tokens=5,
            temperature=0,
        )
        raw = response.choices[0].message.content or ""
        intent = _parse_label(raw)
        if intent:
            logger.debug("LLM classifier → %s (raw: %r)", intent, raw)
            return intent
        logger.warning("LLM classifier returned unexpected label %r — falling back", raw)
    except Exception as exc:
        logger.warning("LLM classifier failed (%s) — falling back to heuristic", exc)

    return classify_intent(messages)


async def classify_intent_gemini(
    messages: list[ChatMessage],
    genai_client: Any,
    model: str,
) -> str:
    """
    Classify intent using the Google Gemini async client.
    Falls back to the heuristic classifier on any error.
    """
    try:
        from google.genai import types as gtypes

        response = await genai_client.aio.models.generate_content(
            model=model,
            contents=_build_prompt(messages),
            config=gtypes.GenerateContentConfig(
                max_output_tokens=5,
                temperature=0,
            ),
        )
        raw = response.text or ""
        intent = _parse_label(raw)
        if intent:
            logger.debug("Gemini classifier → %s (raw: %r)", intent, raw)
            return intent
        logger.warning("Gemini classifier returned unexpected label %r — falling back", raw)
    except Exception as exc:
        logger.warning("Gemini classifier failed (%s) — falling back to heuristic", exc)

    return classify_intent(messages)


# ---------------------------------------------------------------------------
# Per-intent system-prompt injections
# ---------------------------------------------------------------------------

INTENT_LABEL: dict[str, str] = {
    "analysis":   "InVEST Analysis",
    "geospatial": "Geospatial Operation",
    "followup":   "Follow-up Question",
}

INTENT_HINT: dict[str, str] = {
    "analysis": "",   # default — no extra hint needed

    "geospatial": (
        "\n\n## Routing: Geospatial Operation\n"
        "The user is requesting a QGIS geospatial operation. "
        "Prefer QGIS tools: reproject_raster, clip_raster_by_mask, buffer_vector, "
        "vector_overlay, zonal_statistics, raster_calculator, render_map, execute_processing. "
        "Call get_raster_info or get_vector_info first if you need layer metadata. "
        "Report the output file path when done."
    ),

    "followup": (
        "\n\n## Routing: Follow-up Question\n"
        "This is a follow-up question about results already shown in the conversation. "
        "Answer using the context you already have — do NOT call any tools "
        "unless the user explicitly asks to run something new. "
        "Be concise and scientifically precise."
    ),
}
