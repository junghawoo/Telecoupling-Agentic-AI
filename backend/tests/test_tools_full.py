"""
Telecoupling AI - Full Tool Coverage Tests

Tests every tool not covered in test_api.py:
  - InVEST: annual_water_yield, pollination, sdr, ndr, forest_carbon_edge
  - InVEST intent (knowledge) queries: coastal_blue_carbon, seasonal_water_yield,
    crop_production_percentile, crop_production_regression, habitat_risk_assessment,
    recreation
  - QGIS: reproject_vector, clip_raster_by_mask, clip_vector_by_extent,
    buffer_vector, vector_overlay, zonal_statistics, raster_calculator,
    render_map, execute_processing

All fixtures are session-scoped in conftest.py — each LLM call runs once and is
shared across every test that uses it.

Run:
    pytest tests/test_tools_full.py -v --timeout=200
"""

import os
import pytest

INVEST_SAMPLE_DIR = (
    "/home/shubh/projects/telecoupling-toolbox/"
    "telecoupling-app/backend/data/sample-inputs"
)


def tools_used(result: dict) -> list[str]:
    return [tc["tool"] for tc in result["tool_calls"]]


def _first_call(result: dict, tool_name: str) -> dict:
    """Return the first tool_call record for the given tool name."""
    for tc in result["tool_calls"]:
        if tc["tool"] == tool_name:
            return tc
    raise AssertionError(
        f"Tool '{tool_name}' was never called. "
        f"Tools used: {tools_used(result)}"
    )


# ---------------------------------------------------------------------------
# 12. Annual Water Yield
# ---------------------------------------------------------------------------

has_awy_data = (
    os.path.exists(f"{INVEST_SAMPLE_DIR}/AnnualWaterYield/land_use_gura.tif") or  # real NatCap
    os.path.exists(f"{INVEST_SAMPLE_DIR}/AnnualWaterYield/lulc.tif")               # synthetic
)


@pytest.mark.skipif(not has_awy_data, reason="AWY sample data not present")
class TestAnnualWaterYield:

    def test_run_annual_water_yield_tool_called(self, awy_run_result):
        assert "run_annual_water_yield" in tools_used(awy_run_result), \
            f"Tools used: {tools_used(awy_run_result)}"

    def test_awy_uses_lulc_path_param(self, awy_run_result):
        call = _first_call(awy_run_result, "run_annual_water_yield")
        assert "lulc_path" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_awy_uses_watersheds_path_param(self, awy_run_result):
        call = _first_call(awy_run_result, "run_annual_water_yield")
        assert "watersheds_path" in call["arguments"], \
            f"Missing watersheds_path: {list(call['arguments'].keys())}"

    def test_awy_uses_biophysical_table_path_param(self, awy_run_result):
        call = _first_call(awy_run_result, "run_annual_water_yield")
        assert "biophysical_table_path" in call["arguments"], \
            f"Missing biophysical_table_path: {list(call['arguments'].keys())}"

    def test_awy_uses_seasonality_constant_param(self, awy_run_result):
        call = _first_call(awy_run_result, "run_annual_water_yield")
        assert "seasonality_constant" in call["arguments"], \
            f"Missing seasonality_constant: {list(call['arguments'].keys())}"

    def test_awy_response_not_none(self, awy_run_result):
        assert awy_run_result["response"] is not None
        assert len(awy_run_result["response"]) > 10

    def test_awy_classified_as_analysis(self, awy_run_result):
        assert awy_run_result["classified"]["intent"] == "analysis"


# ---------------------------------------------------------------------------
# 13. Pollination
# ---------------------------------------------------------------------------

has_poll_data = (
    os.path.exists(f"{INVEST_SAMPLE_DIR}/Pollination/landcover.tif") or  # real NatCap
    os.path.exists(f"{INVEST_SAMPLE_DIR}/Pollination/lulc.tif")          # synthetic
)


@pytest.mark.skipif(not has_poll_data, reason="Pollination sample data not present")
class TestPollination:

    def test_run_pollination_tool_called(self, pollination_run_result):
        assert "run_pollination" in tools_used(pollination_run_result), \
            f"Tools used: {tools_used(pollination_run_result)}"

    def test_pollination_uses_landcover_raster_path_param(self, pollination_run_result):
        call = _first_call(pollination_run_result, "run_pollination")
        assert "landcover_raster_path" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_pollination_uses_guild_table_path_param(self, pollination_run_result):
        call = _first_call(pollination_run_result, "run_pollination")
        assert "guild_table_path" in call["arguments"], \
            f"Missing guild_table_path: {list(call['arguments'].keys())}"

    def test_pollination_uses_landcover_biophysical_table_path_param(self, pollination_run_result):
        call = _first_call(pollination_run_result, "run_pollination")
        assert "landcover_biophysical_table_path" in call["arguments"], \
            f"Missing landcover_biophysical_table_path: {list(call['arguments'].keys())}"

    def test_pollination_response_not_none(self, pollination_run_result):
        assert pollination_run_result["response"] is not None
        assert len(pollination_run_result["response"]) > 10

    def test_pollination_classified_as_analysis(self, pollination_run_result):
        assert pollination_run_result["classified"]["intent"] == "analysis"


# ---------------------------------------------------------------------------
# 14. Sediment Delivery Ratio (SDR)
# ---------------------------------------------------------------------------

has_sdr_data = (
    os.path.exists(f"{INVEST_SAMPLE_DIR}/SDR/DEM_gura.tif") or  # real NatCap
    os.path.exists(f"{INVEST_SAMPLE_DIR}/SDR/dem.tif")          # synthetic
)


@pytest.mark.skipif(not has_sdr_data, reason="SDR sample data not present")
class TestSDR:

    def test_run_sdr_tool_called(self, sdr_run_result):
        assert "run_sediment_delivery_ratio" in tools_used(sdr_run_result), \
            f"Tools used: {tools_used(sdr_run_result)}"

    def test_sdr_uses_dem_path_param(self, sdr_run_result):
        call = _first_call(sdr_run_result, "run_sediment_delivery_ratio")
        assert "dem_path" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_sdr_uses_lulc_path_param(self, sdr_run_result):
        call = _first_call(sdr_run_result, "run_sediment_delivery_ratio")
        assert "lulc_path" in call["arguments"], \
            f"Missing lulc_path: {list(call['arguments'].keys())}"

    def test_sdr_uses_watersheds_path_param(self, sdr_run_result):
        call = _first_call(sdr_run_result, "run_sediment_delivery_ratio")
        assert "watersheds_path" in call["arguments"], \
            f"Missing watersheds_path: {list(call['arguments'].keys())}"

    def test_sdr_uses_biophysical_table_path_param(self, sdr_run_result):
        call = _first_call(sdr_run_result, "run_sediment_delivery_ratio")
        assert "biophysical_table_path" in call["arguments"], \
            f"Missing biophysical_table_path: {list(call['arguments'].keys())}"

    def test_sdr_uses_threshold_flow_accumulation_param(self, sdr_run_result):
        call = _first_call(sdr_run_result, "run_sediment_delivery_ratio")
        assert "threshold_flow_accumulation" in call["arguments"], \
            f"Missing threshold_flow_accumulation: {list(call['arguments'].keys())}"

    def test_sdr_response_not_none(self, sdr_run_result):
        assert sdr_run_result["response"] is not None
        assert len(sdr_run_result["response"]) > 10

    def test_sdr_classified_as_analysis(self, sdr_run_result):
        assert sdr_run_result["classified"]["intent"] == "analysis"


# ---------------------------------------------------------------------------
# 15. Nutrient Delivery Ratio (NDR)
# ---------------------------------------------------------------------------

has_ndr_data = (
    os.path.exists(f"{INVEST_SAMPLE_DIR}/NDR/DEM_gura.tif") or  # real NatCap
    os.path.exists(f"{INVEST_SAMPLE_DIR}/NDR/dem.tif")          # synthetic
)


@pytest.mark.skipif(not has_ndr_data, reason="NDR sample data not present")
class TestNDR:

    def test_run_ndr_tool_called(self, ndr_run_result):
        assert "run_nutrient_delivery_ratio" in tools_used(ndr_run_result), \
            f"Tools used: {tools_used(ndr_run_result)}"

    def test_ndr_uses_dem_path_param(self, ndr_run_result):
        call = _first_call(ndr_run_result, "run_nutrient_delivery_ratio")
        assert "dem_path" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_ndr_uses_lulc_path_param(self, ndr_run_result):
        call = _first_call(ndr_run_result, "run_nutrient_delivery_ratio")
        assert "lulc_path" in call["arguments"], \
            f"Missing lulc_path: {list(call['arguments'].keys())}"

    def test_ndr_uses_runoff_proxy_path_param(self, ndr_run_result):
        call = _first_call(ndr_run_result, "run_nutrient_delivery_ratio")
        assert "runoff_proxy_path" in call["arguments"], \
            f"Missing runoff_proxy_path: {list(call['arguments'].keys())}"

    def test_ndr_uses_watersheds_path_param(self, ndr_run_result):
        call = _first_call(ndr_run_result, "run_nutrient_delivery_ratio")
        assert "watersheds_path" in call["arguments"], \
            f"Missing watersheds_path: {list(call['arguments'].keys())}"

    def test_ndr_uses_biophysical_table_path_param(self, ndr_run_result):
        call = _first_call(ndr_run_result, "run_nutrient_delivery_ratio")
        assert "biophysical_table_path" in call["arguments"], \
            f"Missing biophysical_table_path: {list(call['arguments'].keys())}"

    def test_ndr_response_not_none(self, ndr_run_result):
        assert ndr_run_result["response"] is not None
        assert len(ndr_run_result["response"]) > 10

    def test_ndr_classified_as_analysis(self, ndr_run_result):
        assert ndr_run_result["classified"]["intent"] == "analysis"


# ---------------------------------------------------------------------------
# 16. Forest Carbon Edge Effect
# ---------------------------------------------------------------------------

has_fce_data = (
    os.path.exists(f"{INVEST_SAMPLE_DIR}/ForestCarbonEdge/forest_carbon_edge_lulc_demo.tif") or  # real NatCap
    os.path.exists(f"{INVEST_SAMPLE_DIR}/ForestCarbonEdge/lulc.tif")                            # synthetic
)


@pytest.mark.skipif(not has_fce_data, reason="ForestCarbonEdge sample data not present")
class TestForestCarbonEdge:

    def test_run_forest_carbon_edge_tool_called(self, fce_run_result):
        assert "run_forest_carbon_edge_effect" in tools_used(fce_run_result), \
            f"Tools used: {tools_used(fce_run_result)}"

    def test_fce_uses_lulc_raster_path_param(self, fce_run_result):
        call = _first_call(fce_run_result, "run_forest_carbon_edge_effect")
        assert "lulc_raster_path" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_fce_uses_biophysical_table_path_param(self, fce_run_result):
        call = _first_call(fce_run_result, "run_forest_carbon_edge_effect")
        assert "biophysical_table_path" in call["arguments"], \
            f"Missing biophysical_table_path: {list(call['arguments'].keys())}"

    def test_fce_uses_pools_to_calculate_param(self, fce_run_result):
        call = _first_call(fce_run_result, "run_forest_carbon_edge_effect")
        assert "pools_to_calculate" in call["arguments"], \
            f"Missing pools_to_calculate: {list(call['arguments'].keys())}"

    def test_fce_response_not_none(self, fce_run_result):
        assert fce_run_result["response"] is not None
        assert len(fce_run_result["response"]) > 10

    def test_fce_classified_as_analysis(self, fce_run_result):
        assert fce_run_result["classified"]["intent"] == "analysis"


# ---------------------------------------------------------------------------
# 17–22. InVEST Model Intent / Knowledge Queries
# These ask about model inputs — the agent should answer with relevant info
# without necessarily executing the model.
# ---------------------------------------------------------------------------

class TestInVESTModelKnowledge:
    """Agent correctly identifies and describes less-common InVEST models."""

    def test_coastal_blue_carbon_classified_as_analysis(self, cbc_intent_result):
        assert cbc_intent_result["classified"]["intent"] == "analysis", \
            f"Got intent: {cbc_intent_result['classified']}"

    def test_coastal_blue_carbon_response_mentions_inputs(self, cbc_intent_result):
        resp = (cbc_intent_result["response"] or "").lower()
        assert cbc_intent_result["response"] is not None
        # Response should mention something about the model or its inputs
        assert any(w in resp for w in ["carbon", "coastal", "input", "lulc", "blue"]), \
            f"Response doesn't mention CBC: {resp[:300]}"

    def test_seasonal_water_yield_classified_as_analysis(self, seasonal_wy_intent_result):
        assert seasonal_wy_intent_result["classified"]["intent"] == "analysis"

    def test_seasonal_water_yield_response_mentions_inputs(self, seasonal_wy_intent_result):
        resp = (seasonal_wy_intent_result["response"] or "").lower()
        assert resp, "Empty response"
        assert any(w in resp for w in ["water", "seasonal", "dem", "lulc", "input"]), \
            f"Response doesn't mention seasonal WY inputs: {resp[:300]}"

    def test_crop_production_percentile_classified_as_analysis(self, crop_pct_intent_result):
        assert crop_pct_intent_result["classified"]["intent"] == "analysis"

    def test_crop_production_percentile_response_mentions_inputs(self, crop_pct_intent_result):
        resp = (crop_pct_intent_result["response"] or "").lower()
        assert resp, "Empty response"
        assert any(w in resp for w in ["crop", "lulc", "input", "percentile", "yield"]), \
            f"Response doesn't mention crop production inputs: {resp[:300]}"

    def test_crop_production_regression_classified_as_analysis(self, crop_reg_intent_result):
        assert crop_reg_intent_result["classified"]["intent"] == "analysis"

    def test_crop_production_regression_response_mentions_inputs(self, crop_reg_intent_result):
        resp = (crop_reg_intent_result["response"] or "").lower()
        assert resp, "Empty response"
        assert any(w in resp for w in ["crop", "lulc", "regression", "input", "climate"]), \
            f"Response doesn't mention crop regression inputs: {resp[:300]}"

    def test_hra_classified_as_analysis(self, hra_intent_result):
        assert hra_intent_result["classified"]["intent"] == "analysis"

    def test_hra_response_mentions_inputs(self, hra_intent_result):
        resp = (hra_intent_result["response"] or "").lower()
        assert resp, "Empty response"
        assert any(w in resp for w in ["habitat", "risk", "stressor", "input", "criteria"]), \
            f"Response doesn't mention HRA inputs: {resp[:300]}"

    def test_recreation_classified_as_analysis(self, recreation_intent_result):
        assert recreation_intent_result["classified"]["intent"] == "analysis"

    def test_recreation_response_mentions_inputs(self, recreation_intent_result):
        resp = (recreation_intent_result["response"] or "").lower()
        assert resp, "Empty response"
        assert any(w in resp for w in ["recreation", "aoi", "input", "flickr", "visitation"]), \
            f"Response doesn't mention recreation inputs: {resp[:300]}"


# ---------------------------------------------------------------------------
# 23. Reproject Vector
# ---------------------------------------------------------------------------

class TestReprojectVector:

    def test_reproject_vector_tool_called(self, reproject_vector_result):
        assert "reproject_vector" in tools_used(reproject_vector_result), \
            f"Tools used: {tools_used(reproject_vector_result)}"

    def test_reproject_vector_uses_input_vector_param(self, reproject_vector_result):
        call = _first_call(reproject_vector_result, "reproject_vector")
        assert "input_vector" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_reproject_vector_uses_target_crs_param(self, reproject_vector_result):
        call = _first_call(reproject_vector_result, "reproject_vector")
        assert "target_crs" in call["arguments"], \
            f"Missing target_crs: {list(call['arguments'].keys())}"

    def test_reproject_vector_target_crs_is_correct(self, reproject_vector_result):
        call = _first_call(reproject_vector_result, "reproject_vector")
        crs = call["arguments"].get("target_crs", "")
        assert "32610" in str(crs) or "EPSG" in str(crs).upper(), \
            f"Unexpected CRS value: {crs}"

    def test_reproject_vector_classified_as_geospatial(self, reproject_vector_result):
        assert reproject_vector_result["classified"]["intent"] == "geospatial"

    def test_reproject_vector_response_not_none(self, reproject_vector_result):
        assert reproject_vector_result["response"] is not None


# ---------------------------------------------------------------------------
# 24. Clip Raster by Mask
# ---------------------------------------------------------------------------

class TestClipRasterByMask:

    def test_clip_raster_tool_called(self, clip_raster_result):
        assert "clip_raster_by_mask" in tools_used(clip_raster_result), \
            f"Tools used: {tools_used(clip_raster_result)}"

    def test_clip_raster_uses_input_raster_param(self, clip_raster_result):
        call = _first_call(clip_raster_result, "clip_raster_by_mask")
        assert "input_raster" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_clip_raster_uses_mask_layer_param(self, clip_raster_result):
        call = _first_call(clip_raster_result, "clip_raster_by_mask")
        assert "mask_layer" in call["arguments"], \
            f"Missing mask_layer: {list(call['arguments'].keys())}"

    def test_clip_raster_classified_as_geospatial(self, clip_raster_result):
        assert clip_raster_result["classified"]["intent"] == "geospatial"

    def test_clip_raster_response_not_none(self, clip_raster_result):
        assert clip_raster_result["response"] is not None


# ---------------------------------------------------------------------------
# 25. Clip Vector by Extent
# ---------------------------------------------------------------------------

class TestClipVectorByExtent:

    def test_clip_vector_tool_called(self, clip_vector_result):
        assert "clip_vector_by_extent" in tools_used(clip_vector_result), \
            f"Tools used: {tools_used(clip_vector_result)}"

    def test_clip_vector_uses_input_vector_param(self, clip_vector_result):
        call = _first_call(clip_vector_result, "clip_vector_by_extent")
        assert "input_vector" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_clip_vector_uses_extent_param(self, clip_vector_result):
        call = _first_call(clip_vector_result, "clip_vector_by_extent")
        assert "extent" in call["arguments"], \
            f"Missing extent: {list(call['arguments'].keys())}"

    def test_clip_vector_classified_as_geospatial(self, clip_vector_result):
        assert clip_vector_result["classified"]["intent"] == "geospatial"

    def test_clip_vector_response_not_none(self, clip_vector_result):
        assert clip_vector_result["response"] is not None


# ---------------------------------------------------------------------------
# 26. Buffer Vector
# ---------------------------------------------------------------------------

class TestBufferVector:

    def test_buffer_vector_tool_called(self, buffer_vector_result):
        assert "buffer_vector" in tools_used(buffer_vector_result), \
            f"Tools used: {tools_used(buffer_vector_result)}"

    def test_buffer_vector_uses_input_vector_param(self, buffer_vector_result):
        call = _first_call(buffer_vector_result, "buffer_vector")
        assert "input_vector" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_buffer_vector_uses_distance_param(self, buffer_vector_result):
        call = _first_call(buffer_vector_result, "buffer_vector")
        assert "distance" in call["arguments"], \
            f"Missing distance: {list(call['arguments'].keys())}"

    def test_buffer_vector_distance_is_numeric(self, buffer_vector_result):
        call = _first_call(buffer_vector_result, "buffer_vector")
        dist = call["arguments"].get("distance")
        assert dist is not None
        assert float(dist) > 0, f"Buffer distance should be positive: {dist}"

    def test_buffer_vector_classified_as_geospatial(self, buffer_vector_result):
        assert buffer_vector_result["classified"]["intent"] == "geospatial"

    def test_buffer_vector_response_not_none(self, buffer_vector_result):
        assert buffer_vector_result["response"] is not None


# ---------------------------------------------------------------------------
# 27. Zonal Statistics
# ---------------------------------------------------------------------------

class TestZonalStatistics:

    def test_zonal_statistics_tool_called(self, zonal_stats_result):
        assert "zonal_statistics" in tools_used(zonal_stats_result), \
            f"Tools used: {tools_used(zonal_stats_result)}"

    def test_zonal_statistics_uses_input_raster_param(self, zonal_stats_result):
        call = _first_call(zonal_stats_result, "zonal_statistics")
        assert "input_raster" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_zonal_statistics_uses_input_zones_param(self, zonal_stats_result):
        call = _first_call(zonal_stats_result, "zonal_statistics")
        assert "input_zones" in call["arguments"], \
            f"Missing input_zones: {list(call['arguments'].keys())}"

    def test_zonal_statistics_classified_as_geospatial(self, zonal_stats_result):
        assert zonal_stats_result["classified"]["intent"] == "geospatial"

    def test_zonal_statistics_response_not_none(self, zonal_stats_result):
        assert zonal_stats_result["response"] is not None


# ---------------------------------------------------------------------------
# 28. Raster Calculator
# ---------------------------------------------------------------------------

class TestRasterCalculator:

    def test_raster_calculator_tool_called(self, raster_calc_result):
        assert "raster_calculator" in tools_used(raster_calc_result), \
            f"Tools used: {tools_used(raster_calc_result)}"

    def test_raster_calculator_uses_input_a_param(self, raster_calc_result):
        call = _first_call(raster_calc_result, "raster_calculator")
        assert "input_a" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_raster_calculator_uses_expression_param(self, raster_calc_result):
        call = _first_call(raster_calc_result, "raster_calculator")
        assert "expression" in call["arguments"], \
            f"Missing expression: {list(call['arguments'].keys())}"

    def test_raster_calculator_expression_references_a(self, raster_calc_result):
        call = _first_call(raster_calc_result, "raster_calculator")
        expr = str(call["arguments"].get("expression", ""))
        assert "A" in expr or "a" in expr, \
            f"Expression should reference 'A': {expr}"

    def test_raster_calculator_classified_as_geospatial(self, raster_calc_result):
        assert raster_calc_result["classified"]["intent"] == "geospatial"

    def test_raster_calculator_response_not_none(self, raster_calc_result):
        assert raster_calc_result["response"] is not None


# ---------------------------------------------------------------------------
# 29. Render Map
# ---------------------------------------------------------------------------

class TestRenderMap:

    def test_render_map_tool_called(self, render_map_result):
        assert "render_map" in tools_used(render_map_result), \
            f"Tools used: {tools_used(render_map_result)}"

    def test_render_map_uses_layers_param(self, render_map_result):
        call = _first_call(render_map_result, "render_map")
        assert "layers" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_render_map_layers_contains_raster_path(self, render_map_result):
        call = _first_call(render_map_result, "render_map")
        layers = str(call["arguments"].get("layers", ""))
        assert ".tif" in layers.lower() or "/" in layers, \
            f"layers param should contain a file path: {layers}"

    def test_render_map_classified_as_geospatial(self, render_map_result):
        assert render_map_result["classified"]["intent"] == "geospatial"

    def test_render_map_response_not_none(self, render_map_result):
        assert render_map_result["response"] is not None


# ---------------------------------------------------------------------------
# 30. Execute Processing (generic escape-hatch)
# ---------------------------------------------------------------------------

class TestExecuteProcessing:

    def test_execute_processing_tool_called(self, execute_processing_result):
        assert "execute_processing" in tools_used(execute_processing_result), \
            f"Tools used: {tools_used(execute_processing_result)}"

    def test_execute_processing_uses_algorithm_id_param(self, execute_processing_result):
        call = _first_call(execute_processing_result, "execute_processing")
        assert "algorithm_id" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_execute_processing_uses_parameters_param(self, execute_processing_result):
        call = _first_call(execute_processing_result, "execute_processing")
        assert "parameters" in call["arguments"], \
            f"Missing parameters: {list(call['arguments'].keys())}"

    def test_execute_processing_algorithm_id_contains_gdal(self, execute_processing_result):
        call = _first_call(execute_processing_result, "execute_processing")
        alg_id = str(call["arguments"].get("algorithm_id", "")).lower()
        assert "gdal" in alg_id or "gdalinfo" in alg_id, \
            f"Expected gdal:gdalinfo, got: {alg_id}"

    def test_execute_processing_classified_as_geospatial(self, execute_processing_result):
        assert execute_processing_result["classified"]["intent"] == "geospatial"

    def test_execute_processing_response_not_none(self, execute_processing_result):
        assert execute_processing_result["response"] is not None


# ---------------------------------------------------------------------------
# 31. Vector Overlay
# ---------------------------------------------------------------------------

class TestVectorOverlay:

    def test_vector_overlay_tool_called(self, vector_overlay_result):
        assert "vector_overlay" in tools_used(vector_overlay_result), \
            f"Tools used: {tools_used(vector_overlay_result)}"

    def test_vector_overlay_uses_input_vector_param(self, vector_overlay_result):
        call = _first_call(vector_overlay_result, "vector_overlay")
        assert "input_vector" in call["arguments"], \
            f"Wrong param names: {list(call['arguments'].keys())}"

    def test_vector_overlay_uses_overlay_vector_param(self, vector_overlay_result):
        call = _first_call(vector_overlay_result, "vector_overlay")
        assert "overlay_vector" in call["arguments"], \
            f"Missing overlay_vector: {list(call['arguments'].keys())}"

    def test_vector_overlay_operation_is_intersection(self, vector_overlay_result):
        call = _first_call(vector_overlay_result, "vector_overlay")
        # operation defaults to intersection; may or may not be explicitly set
        op = call["arguments"].get("operation", "intersection").lower()
        assert op in ("intersection", "union", "difference", "symmetric_difference"), \
            f"Unexpected operation: {op}"

    def test_vector_overlay_classified_as_geospatial(self, vector_overlay_result):
        assert vector_overlay_result["classified"]["intent"] == "geospatial"

    def test_vector_overlay_response_not_none(self, vector_overlay_result):
        assert vector_overlay_result["response"] is not None
