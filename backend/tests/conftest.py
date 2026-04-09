"""
Shared pytest fixtures for Telecoupling AI tests.

LLM calls are expensive (~30-90s each with llama3.3:70b).
Session-scoped fixtures run each prompt ONCE and share the result
across every test that needs it.

The Purdue GenAI API has rate limits. Each session fixture adds a small
sleep after the call to avoid hammering the endpoint.
"""

import json
import os
import time
import pytest
import requests as _requests

BASE_URL = "http://localhost:8000"
_AGENT_TIMEOUT = 240  # seconds — raised from 180 to handle late-session API slowdowns

QGIS_SAMPLE_DIR = "/home/shubh/projects/telecoupling-toolbox/telecoupling-app/mcp-servers/qgis-mcp/data"
SAMPLE_RASTER = f"{QGIS_SAMPLE_DIR}/sample.tif"
SAMPLE_VECTOR = f"{QGIS_SAMPLE_DIR}/sample.geojson"


def _sse_collect(messages: list[dict], timeout: int = _AGENT_TIMEOUT, _retry: int = 3) -> dict:
    """POST /agent/chat using requests (streaming) and collect all SSE events.

    Retries up to `_retry` times on:
      - Purdue API rate-limit errors  ("NoneType", "choices")
      - Connection/read timeouts      (requests.exceptions.ConnectionError)
    """
    for attempt in range(_retry + 1):
        try:
            result = _sse_collect_once(messages, timeout)
        except _requests.exceptions.ConnectionError as exc:
            # Read timeout or connection reset mid-stream — treat as transient
            if attempt < _retry:
                wait = 20 * (attempt + 1)
                time.sleep(wait)
                continue
            # Exhausted retries — return an error-shaped dict
            return {
                "classified": None, "thinking_iterations": 0,
                "tool_calls": [], "response": None,
                "error": {"message": str(exc)}, "job_id": None, "raw_events": [],
            }
        # Success or non-transient error (e.g. the model just answered without tools)
        if result["error"] is None:
            return result
        err_msg = (result["error"] or {}).get("message", "")
        if "NoneType" not in err_msg and "choices" not in err_msg:
            return result  # not a rate-limit error, return as-is
        if attempt < _retry:
            time.sleep(15 * (attempt + 1))  # back off 15s, 30s, 45s
    return result


def _sse_collect_once(messages: list[dict], timeout: int) -> dict:
    """Single attempt at collecting SSE events."""
    result = {
        "classified": None,
        "thinking_iterations": 0,
        "tool_calls": [],
        "response": None,
        "error": None,
        "job_id": None,
        "raw_events": [],
    }
    with _requests.post(
        f"{BASE_URL}/agent/chat",
        json={"messages": messages},
        headers={"Accept": "text/event-stream"},
        stream=True,
        timeout=timeout,
    ) as resp:
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            raw = raw_line[5:].strip()
            if raw == "[DONE]":
                break
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            result["raw_events"].append(event)
            t = event.get("type")
            if t == "classified":
                result["classified"] = event["data"]
            elif t == "thinking":
                result["thinking_iterations"] = max(
                    result["thinking_iterations"],
                    event["data"].get("iteration", 0),
                )
            elif t == "tool_call":
                result["tool_calls"].append({
                    "tool": event["data"]["tool"],
                    "arguments": event["data"].get("arguments", {}),
                })
            elif t == "tool_result":
                if result["tool_calls"]:
                    result["tool_calls"][-1]["result_preview"] = event["data"].get("preview", "")
                    result["tool_calls"][-1]["success"] = event["data"].get("success", False)
            elif t == "response":
                result["response"] = event["data"].get("text", "")
                result["job_id"] = event["data"].get("job_id")
            elif t == "error":
                result["error"] = event["data"]
    return result


# ---------------------------------------------------------------------------
# Session-scoped cached results — one LLM call each, reused by all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def invest_list_result():
    r = _sse_collect([{"role": "user", "content": "List all available InVEST models"}])
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def qgis_list_result():
    r = _sse_collect([{"role": "user", "content": "List all available QGIS tools"}])
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def followup_result():
    r = _sse_collect([
        {"role": "user", "content": "Run carbon storage analysis"},
        {"role": "model", "content": "The carbon storage model completed successfully."},
        {"role": "user", "content": "Can you explain what carbon sequestration means?"},
    ])
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def geospatial_intent_result():
    r = _sse_collect([{"role": "user", "content": "Reproject a raster to EPSG:4326"}])
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def algo_details_result():
    r = _sse_collect([{"role": "user", "content": "Show me the parameters for the native:buffer QGIS algorithm"}])
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def list_algorithms_result():
    r = _sse_collect([{"role": "user", "content": "List QGIS processing algorithms"}])
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def what_can_you_do_result():
    r = _sse_collect([{"role": "user", "content": "What can you do?"}])
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def multi_turn_result():
    r = _sse_collect([
        {"role": "user", "content": "List InVEST models"},
        {"role": "model", "content": "Available models include carbon_storage, habitat_quality, water yield..."},
        {"role": "user", "content": "How many models did you just list?"},
    ])
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def raster_info_result():
    import os
    if not os.path.exists(SAMPLE_RASTER):
        pytest.skip("Sample raster not found")
    r = _sse_collect([{"role": "user", "content": f"Get metadata info for this raster: {SAMPLE_RASTER}"}])
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def vector_info_result():
    import os
    if not os.path.exists(SAMPLE_VECTOR):
        pytest.skip("Sample vector not found")
    r = _sse_collect([{"role": "user", "content": f"Get metadata for this vector file: {SAMPLE_VECTOR}"}])
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def reproject_result():
    import os
    if not os.path.exists(SAMPLE_RASTER):
        pytest.skip("Sample raster not found")
    r = _sse_collect([{"role": "user", "content": f"Reproject this raster to EPSG:4326: {SAMPLE_RASTER}"}])
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def carbon_run_result():
    # Prefer real NatCap Carbon data if present, else let the agent use get_sample_args
    CS = f"{_B}/Carbon"
    if os.path.exists(f"{CS}/lulc_current_willamette.tif"):
        content = (
            f"Run carbon storage analysis with these exact file paths: "
            f"lulc_cur_path={CS}/lulc_current_willamette.tif, "
            f"carbon_pools_path={CS}/carbon_pools_willamette.csv"
        )
    else:
        content = "Run carbon storage analysis using sample data"
    r = _sse_collect([{"role": "user", "content": content}], timeout=360)
    time.sleep(8)
    return r


@pytest.fixture(scope="session")
def hq_run_result():
    # Prefer real NatCap HabitatQuality data if present
    HQ_REAL = f"{_B}/HabitatQuality"
    HQ_SYN  = f"{_B}/HabitatQuality/HabitatQuality"
    if os.path.exists(f"{HQ_REAL}/lulc_current_willamette.tif"):
        HQ = HQ_REAL
    else:
        HQ = HQ_SYN
    r = _sse_collect(
        [{"role": "user", "content": (
            f"Run habitat quality analysis with these exact file paths: "
            f"lulc_cur_path={HQ}/lulc_current_willamette.tif, "
            f"threats_table_path={HQ}/threats_willamette.csv, "
            f"sensitivity_table_path={HQ}/sensitivity_willamette.csv, "
            f"access_vector_path={HQ}/accessibility_willamette.shp, "
            f"half_saturation_constant=0.05"
        )}],
        timeout=360,
    )
    time.sleep(8)
    return r


# ---------------------------------------------------------------------------
# New InVEST model fixtures
# ---------------------------------------------------------------------------

_B = "/home/shubh/projects/telecoupling-toolbox/telecoupling-app/backend/data/sample-inputs"

# ---------------------------------------------------------------------------
# Path resolution helpers: prefer real NatCap data if downloaded, else synthetic.
# Run  python download_sample_data.py  from the telecoupling-app/ directory to
# download the official sample datasets (~10 MB total for the models below).
# ---------------------------------------------------------------------------

def _awy_paths() -> dict:
    """Annual Water Yield — real NatCap filenames take priority over synthetic."""
    D = f"{_B}/AnnualWaterYield"
    real = f"{D}/land_use_gura.tif"
    if os.path.exists(real):
        return {
            "lulc_path":                     f"{D}/land_use_gura.tif",
            "depth_to_root_rest_layer_path": f"{D}/depth_to_root_restricting_layer_gura.tif",
            "precipitation_path":            f"{D}/precipitation_gura.tif",
            "pawc_path":                     f"{D}/plant_available_water_fraction_gura.tif",
            "eto_path":                      f"{D}/reference_ET_gura.tif",
            "watersheds_path":               f"{D}/watershed_gura.shp",
            "biophysical_table_path":        f"{D}/biophysical_table_gura.csv",
        }
    return {
        "lulc_path":                     f"{D}/lulc.tif",
        "depth_to_root_rest_layer_path": f"{D}/depth_root.tif",
        "precipitation_path":            f"{D}/precip.tif",
        "pawc_path":                     f"{D}/pawc.tif",
        "eto_path":                      f"{D}/eto.tif",
        "watersheds_path":               f"{D}/watersheds.shp",
        "biophysical_table_path":        f"{D}/biophysical_table.csv",
    }


def _poll_paths() -> dict:
    D = f"{_B}/Pollination"
    if os.path.exists(f"{D}/landcover.tif"):
        return {
            "landcover_raster_path":            f"{D}/landcover.tif",
            "guild_table_path":                 f"{D}/guild_table.csv",
            "landcover_biophysical_table_path": f"{D}/landcover_biophysical_table.csv",
        }
    return {
        "landcover_raster_path":            f"{D}/lulc.tif",
        "guild_table_path":                 f"{D}/guild_table.csv",
        "landcover_biophysical_table_path": f"{D}/biophysical_table.csv",
    }


def _sdr_paths() -> dict:
    D = f"{_B}/SDR"
    if os.path.exists(f"{D}/DEM_gura.tif"):
        return {
            "dem_path":               f"{D}/DEM_gura.tif",
            "erosivity_path":         f"{D}/erosivity_gura.tif",
            "erodibility_path":       f"{D}/erodibility_gura.tif",
            "lulc_path":              f"{D}/land_use_gura.tif",
            "watersheds_path":        f"{D}/watershed_gura.shp",
            "biophysical_table_path": f"{D}/biophysical_table_Gura.csv",
        }
    return {
        "dem_path":               f"{D}/dem.tif",
        "erosivity_path":         f"{D}/erosivity.tif",
        "erodibility_path":       f"{D}/erodibility.tif",
        "lulc_path":              f"{D}/lulc.tif",
        "watersheds_path":        f"{D}/watersheds.shp",
        "biophysical_table_path": f"{D}/biophysical_table.csv",
    }


def _ndr_paths() -> dict:
    D = f"{_B}/NDR"
    if os.path.exists(f"{D}/DEM_gura.tif"):
        return {
            "dem_path":               f"{D}/DEM_gura.tif",
            "lulc_path":              f"{D}/land_use_gura.tif",
            "runoff_proxy_path":      f"{D}/precipitation_gura.tif",
            "watersheds_path":        f"{D}/watershed_gura.shp",
            "biophysical_table_path": f"{D}/biophysical_table_gura.csv",
        }
    return {
        "dem_path":               f"{D}/dem.tif",
        "lulc_path":              f"{D}/lulc.tif",
        "runoff_proxy_path":      f"{D}/runoff_proxy.tif",
        "watersheds_path":        f"{D}/watersheds.shp",
        "biophysical_table_path": f"{D}/biophysical_table.csv",
    }


def _fce_paths() -> dict:
    D = f"{_B}/ForestCarbonEdge"
    if os.path.exists(f"{D}/forest_carbon_edge_lulc_demo.tif"):
        return {
            "lulc_raster_path":        f"{D}/forest_carbon_edge_lulc_demo.tif",
            "biophysical_table_path":  f"{D}/forest_edge_carbon_lu_table.csv",
            "tropical_model_path":     f"{D}/core_data/forest_carbon_edge_regression_model_parameters.shp",
            "use_edge_effects":        "true",
        }
    return {
        "lulc_raster_path":        f"{D}/lulc.tif",
        "biophysical_table_path":  f"{D}/biophysical_table.csv",
        "tropical_model_path":     None,
        "use_edge_effects":        "false",
    }


@pytest.fixture(scope="session")
def awy_run_result():
    p = _awy_paths()
    r = _sse_collect([{"role": "user", "content": (
        f"Run annual water yield model with: lulc_path={p['lulc_path']}, "
        f"depth_to_root_rest_layer_path={p['depth_to_root_rest_layer_path']}, "
        f"precipitation_path={p['precipitation_path']}, pawc_path={p['pawc_path']}, "
        f"eto_path={p['eto_path']}, watersheds_path={p['watersheds_path']}, "
        f"biophysical_table_path={p['biophysical_table_path']}, seasonality_constant=5"
    )}], timeout=360)
    time.sleep(8); return r

@pytest.fixture(scope="session")
def pollination_run_result():
    p = _poll_paths()
    r = _sse_collect([{"role": "user", "content": (
        f"Run pollination model with: landcover_raster_path={p['landcover_raster_path']}, "
        f"guild_table_path={p['guild_table_path']}, "
        f"landcover_biophysical_table_path={p['landcover_biophysical_table_path']}"
    )}], timeout=360)
    time.sleep(8); return r

@pytest.fixture(scope="session")
def sdr_run_result():
    p = _sdr_paths()
    r = _sse_collect([{"role": "user", "content": (
        f"Run sediment delivery ratio model with: dem_path={p['dem_path']}, "
        f"erosivity_path={p['erosivity_path']}, erodibility_path={p['erodibility_path']}, "
        f"lulc_path={p['lulc_path']}, watersheds_path={p['watersheds_path']}, "
        f"biophysical_table_path={p['biophysical_table_path']}, "
        f"threshold_flow_accumulation=1000, k_param=2, sdr_max=0.8, ic_0_param=0.5, l_max=122"
    )}], timeout=360)
    time.sleep(8); return r

@pytest.fixture(scope="session")
def ndr_run_result():
    p = _ndr_paths()
    r = _sse_collect([{"role": "user", "content": (
        f"Run nutrient delivery ratio model with: dem_path={p['dem_path']}, "
        f"lulc_path={p['lulc_path']}, runoff_proxy_path={p['runoff_proxy_path']}, "
        f"watersheds_path={p['watersheds_path']}, "
        f"biophysical_table_path={p['biophysical_table_path']}, "
        f"calc_p=true, calc_n=true, threshold_flow_accumulation=1000, "
        f"k_param=2, subsurface_critical_length_n=200, subsurface_eff_n=0.8"
    )}], timeout=360)
    time.sleep(8); return r

@pytest.fixture(scope="session")
def fce_run_result():
    p = _fce_paths()
    if p["use_edge_effects"] == "true":
        content = (
            f"Run forest carbon edge effect model with: "
            f"lulc_raster_path={p['lulc_raster_path']}, "
            f"biophysical_table_path={p['biophysical_table_path']}, "
            f"tropical_forest_edge_carbon_model_vector_path={p['tropical_model_path']}, "
            f"n_nearest_model_points=10, biomass_to_carbon_conversion_factor=0.47, "
            f"pools_to_calculate=all, compute_forest_edge_effects=true"
        )
    else:
        content = (
            f"Run forest carbon edge effect model with: "
            f"lulc_raster_path={p['lulc_raster_path']}, "
            f"biophysical_table_path={p['biophysical_table_path']}, "
            f"n_nearest_model_points=10, biomass_to_carbon_conversion_factor=0.47, "
            f"pools_to_calculate=all, compute_forest_edge_effects=false"
        )
    r = _sse_collect([{"role": "user", "content": content}], timeout=360)
    time.sleep(8); return r

@pytest.fixture(scope="session")
def cbc_intent_result():
    """coastal_blue_carbon — just verify agent classifies and attempts the tool."""
    r = _sse_collect([{"role": "user", "content":
        "Run coastal blue carbon analysis — what inputs does it need?"
    }], timeout=120)
    time.sleep(8); return r

@pytest.fixture(scope="session")
def seasonal_wy_intent_result():
    r = _sse_collect([{"role": "user", "content":
        "What inputs are required to run the seasonal water yield model?"
    }], timeout=120)
    time.sleep(8); return r

@pytest.fixture(scope="session")
def crop_pct_intent_result():
    r = _sse_collect([{"role": "user", "content":
        "What inputs does the crop production percentile model need?"
    }], timeout=120)
    time.sleep(8); return r

@pytest.fixture(scope="session")
def crop_reg_intent_result():
    r = _sse_collect([{"role": "user", "content":
        "What inputs does the crop production regression model require?"
    }], timeout=120)
    time.sleep(8); return r

@pytest.fixture(scope="session")
def hra_intent_result():
    r = _sse_collect([{"role": "user", "content":
        "What inputs are needed for habitat risk assessment?"
    }], timeout=120)
    time.sleep(8); return r

@pytest.fixture(scope="session")
def recreation_intent_result():
    r = _sse_collect([{"role": "user", "content":
        "What inputs does the recreation model need?"
    }], timeout=120)
    time.sleep(8); return r

# ---------------------------------------------------------------------------
# New QGIS tool fixtures
# ---------------------------------------------------------------------------

_R = f"{QGIS_SAMPLE_DIR}/sample.tif"
_V = f"{QGIS_SAMPLE_DIR}/sample.geojson"

@pytest.fixture(scope="session")
def reproject_vector_result():
    r = _sse_collect([{"role": "user", "content":
        f"Reproject this vector to EPSG:32610: {_V}"
    }])
    time.sleep(8); return r

@pytest.fixture(scope="session")
def clip_raster_result():
    r = _sse_collect([{"role": "user", "content":
        f"Clip the raster {_R} using the mask layer {_V}"
    }])
    time.sleep(8); return r

@pytest.fixture(scope="session")
def clip_vector_result():
    r = _sse_collect([{"role": "user", "content":
        f"Clip the vector {_V} to its own extent"
    }])
    time.sleep(8); return r

@pytest.fixture(scope="session")
def buffer_vector_result():
    r = _sse_collect([{"role": "user", "content":
        f"Create a 1000 metre buffer around features in {_V}"
    }])
    time.sleep(8); return r

@pytest.fixture(scope="session")
def zonal_stats_result():
    r = _sse_collect([{"role": "user", "content":
        f"Calculate zonal statistics for raster {_R} within zones {_V}"
    }])
    time.sleep(8); return r

@pytest.fixture(scope="session")
def raster_calc_result():
    r = _sse_collect([{"role": "user", "content":
        f"Use the raster calculator to multiply {_R} by 2 and save the result"
    }])
    time.sleep(8); return r

@pytest.fixture(scope="session")
def render_map_result():
    r = _sse_collect([{"role": "user", "content":
        f"Render a map image from the layer {_R}"
    }])
    time.sleep(8); return r

@pytest.fixture(scope="session")
def execute_processing_result():
    r = _sse_collect([{"role": "user", "content":
        f"Use execute_processing to run gdal:gdalinfo on {_R}"
    }])
    time.sleep(8); return r

@pytest.fixture(scope="session")
def vector_overlay_result():
    r = _sse_collect([{"role": "user", "content":
        f"Perform an intersection overlay between {_V} and itself"
    }])
    time.sleep(8); return r

# Function-scoped pass-through for tests that need one-off calls
@pytest.fixture
def sse_collect():
    return _sse_collect
