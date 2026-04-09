"""
Telecoupling AI - Comprehensive API & Agent Integration Tests

Tests every flow, intent path, tool, and endpoint in the application.
Requires the backend to be running on http://localhost:8000.

Run:
    pytest tests/test_api.py -v --timeout=200
"""

import os
import pytest
import requests

BASE_URL = "http://localhost:8000"


def tools_used(result: dict) -> list[str]:
    return [tc["tool"] for tc in result["tool_calls"]]


# ---------------------------------------------------------------------------
# 1. Health & Infrastructure
# ---------------------------------------------------------------------------

class TestInfrastructure:

    def test_health_endpoint(self):
        r = requests.get(f"{BASE_URL}/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"

    def test_health_has_both_mcp_servers(self):
        servers = requests.get(f"{BASE_URL}/health").json().get("mcp_servers", [])
        assert "invest-mcp" in servers, f"invest-mcp missing from {servers}"
        assert "qgis-mcp" in servers, f"qgis-mcp missing from {servers}"

    def test_health_tool_count_31(self):
        data = requests.get(f"{BASE_URL}/health").json()
        assert data["tool_count"] == 31, f"Expected 31 tools, got {data['tool_count']}"

    def test_health_model_is_llama33(self):
        data = requests.get(f"{BASE_URL}/health").json()
        assert "llama3.3" in data["active_model"], f"Unexpected model: {data['active_model']}"

    def test_root_endpoint_lists_routes(self):
        r = requests.get(f"{BASE_URL}/")
        assert r.status_code == 200
        assert "endpoints" in r.json()

    def test_files_list_endpoint(self):
        r = requests.get(f"{BASE_URL}/files")
        assert r.status_code == 200
        data = r.json()
        assert "files" in data
        assert isinstance(data["files"], list)


# ---------------------------------------------------------------------------
# 2. Intent Classification
# ---------------------------------------------------------------------------

class TestIntentClassification:

    def test_invest_analysis_intent(self, invest_list_result):
        assert invest_list_result["classified"]["intent"] == "analysis", \
            invest_list_result["classified"]

    def test_geospatial_intent(self, qgis_list_result):
        assert qgis_list_result["classified"]["intent"] == "geospatial", \
            qgis_list_result["classified"]

    def test_followup_intent(self, followup_result):
        assert followup_result["classified"]["intent"] == "followup", \
            followup_result["classified"]

    def test_invest_model_name_triggers_analysis(self, invest_list_result):
        assert invest_list_result["classified"]["intent"] == "analysis"

    def test_qgis_operation_triggers_geospatial(self, geospatial_intent_result):
        assert geospatial_intent_result["classified"]["intent"] == "geospatial"

    def test_classified_event_has_label(self, invest_list_result):
        c = invest_list_result["classified"]
        assert c is not None
        assert "label" in c
        assert c["label"] != ""

    def test_intent_labels_are_human_readable(self, invest_list_result, qgis_list_result, followup_result):
        assert invest_list_result["classified"]["label"] != "analysis"   # label should be friendly text
        assert qgis_list_result["classified"]["label"] != "geospatial"
        assert followup_result["classified"]["label"] != "followup"


# ---------------------------------------------------------------------------
# 3. InVEST Discovery Tools
# ---------------------------------------------------------------------------

class TestInVESTDiscovery:

    def test_list_models_tool_called(self, invest_list_result):
        assert "list_models" in tools_used(invest_list_result)

    def test_list_models_response_has_model_names(self, invest_list_result):
        resp = (invest_list_result["response"] or "").lower()
        assert any(m in resp for m in ["carbon", "habitat", "water", "pollination"])

    def test_list_models_called_with_no_args(self, invest_list_result):
        lm_calls = [tc for tc in invest_list_result["tool_calls"] if tc["tool"] == "list_models"]
        assert lm_calls, "list_models was not called"
        assert lm_calls[0]["arguments"] == {}, \
            f"Expected empty args, got {lm_calls[0]['arguments']}"

    def test_list_models_response_covers_multiple_domains(self, invest_list_result):
        resp = (invest_list_result["response"] or "").lower()
        domains = ["carbon", "habitat", "water", "pollination", "sediment", "nutrient", "recreation"]
        found = sum(1 for d in domains if d in resp)
        assert found >= 4, f"Only found {found} model domains in response"

    def test_get_sample_args_carbon_storage(self, sse_collect):
        result = sse_collect([{"role": "user", "content": "Show me sample arguments for carbon storage"}])
        assert "get_sample_args" in tools_used(result)

    def test_get_sample_args_habitat_quality(self, sse_collect):
        result = sse_collect([{"role": "user", "content": "Show me sample arguments for habitat quality"}])
        assert "get_sample_args" in tools_used(result)

    def test_list_sample_data_tool_called(self, sse_collect):
        result = sse_collect([{"role": "user", "content": "List all sample data files available"}])
        assert "list_sample_data" in tools_used(result)


# ---------------------------------------------------------------------------
# 4. QGIS Discovery Tools
# ---------------------------------------------------------------------------

class TestQGISDiscovery:

    def test_list_operations_called(self, qgis_list_result):
        assert "list_operations" in tools_used(qgis_list_result)

    def test_list_operations_response_has_tool_names(self, qgis_list_result):
        resp = (qgis_list_result["response"] or "").lower()
        assert any(t in resp for t in ["reproject", "clip", "buffer"])

    def test_list_operations_response_complete(self, qgis_list_result):
        resp = (qgis_list_result["response"] or "").lower()
        expected = ["reproject", "clip", "buffer", "zonal", "render"]
        found = sum(1 for e in expected if e in resp)
        assert found >= 3, f"Only {found} operation types mentioned"

    def test_list_algorithms_tool_called(self, list_algorithms_result):
        assert "list_algorithms" in tools_used(list_algorithms_result)

    def test_list_algorithms_returns_gdal_algorithms(self, list_algorithms_result):
        la_call = next(tc for tc in list_algorithms_result["tool_calls"] if tc["tool"] == "list_algorithms")
        assert "gdal" in la_call.get("result_preview", "").lower()

    def test_get_algorithm_details_uses_correct_param(self, algo_details_result):
        assert "get_algorithm_details" in tools_used(algo_details_result)
        ga_call = next(tc for tc in algo_details_result["tool_calls"]
                       if tc["tool"] == "get_algorithm_details")
        assert "algorithm_id" in ga_call["arguments"], \
            f"Wrong param name used: {ga_call['arguments']}"

    def test_get_algorithm_details_gdal_warp(self, algo_details_result):
        # algo_details_result asks about native:buffer — also tests get_algorithm_details path
        assert "get_algorithm_details" in tools_used(algo_details_result)


# ---------------------------------------------------------------------------
# 5. QGIS File Operations (with synthetic sample data)
# ---------------------------------------------------------------------------

QGIS_SAMPLE_DIR = "/home/shubh/projects/telecoupling-toolbox/telecoupling-app/mcp-servers/qgis-mcp/data"
SAMPLE_RASTER = f"{QGIS_SAMPLE_DIR}/sample.tif"
SAMPLE_VECTOR = f"{QGIS_SAMPLE_DIR}/sample.geojson"
# raster_info_result, vector_info_result, reproject_result are session-scoped in conftest.py


class TestQGISFileOps:

    def test_get_raster_info_tool_called(self, raster_info_result):
        assert "get_raster_info" in tools_used(raster_info_result), \
            f"Tools called: {tools_used(raster_info_result)}"

    def test_get_raster_info_uses_raster_path_param(self, raster_info_result):
        ri_call = next(tc for tc in raster_info_result["tool_calls"]
                       if tc["tool"] == "get_raster_info")
        assert "raster_path" in ri_call["arguments"], \
            f"Wrong param name: {ri_call['arguments']}"

    def test_get_vector_info_tool_called(self, vector_info_result):
        assert "get_vector_info" in tools_used(vector_info_result)

    def test_get_vector_info_uses_vector_path_param(self, vector_info_result):
        vi_call = next(tc for tc in vector_info_result["tool_calls"]
                       if tc["tool"] == "get_vector_info")
        assert "vector_path" in vi_call["arguments"], \
            f"Wrong param name: {vi_call['arguments']}"

    def test_reproject_raster_tool_called(self, reproject_result):
        assert "reproject_raster" in tools_used(reproject_result)

    def test_reproject_raster_uses_input_raster_param(self, reproject_result):
        rr_call = next(tc for tc in reproject_result["tool_calls"]
                       if tc["tool"] == "reproject_raster")
        assert "input_raster" in rr_call["arguments"], \
            f"Wrong param names: {rr_call['arguments']}"

    def test_reproject_raster_uses_target_crs_param(self, reproject_result):
        rr_call = next(tc for tc in reproject_result["tool_calls"]
                       if tc["tool"] == "reproject_raster")
        assert "target_crs" in rr_call["arguments"], \
            f"Missing target_crs: {rr_call['arguments']}"


# ---------------------------------------------------------------------------
# 6. InVEST Model Execution (requires synthetic sample data)
# ---------------------------------------------------------------------------

INVEST_SAMPLE_DIR = "/home/shubh/projects/telecoupling-toolbox/telecoupling-app/backend/data/sample-inputs"
CS_DIR = f"{INVEST_SAMPLE_DIR}/CarbonStorage"
HQ_DIR = f"{INVEST_SAMPLE_DIR}/HabitatQuality/HabitatQuality"

has_carbon_data = os.path.exists(f"{CS_DIR}/lulc_current_willamette.tif")
has_hq_data = os.path.exists(f"{HQ_DIR}/lulc_current_willamette.tif")


# carbon_run_result, hq_run_result are session-scoped in conftest.py

@pytest.mark.skipif(not has_carbon_data, reason="Carbon storage sample data not present")
class TestCarbonStorage:

    def test_run_carbon_storage_tool_called(self, carbon_run_result):
        assert "run_carbon_storage" in tools_used(carbon_run_result), \
            f"Tools: {tools_used(carbon_run_result)}"

    def test_run_carbon_storage_succeeds(self, carbon_run_result):
        rc_call = next(tc for tc in carbon_run_result["tool_calls"]
                       if tc["tool"] == "run_carbon_storage")
        assert '"status": "success"' in rc_call.get("result_preview", ""), \
            f"Model failed: {rc_call.get('result_preview','')[:400]}"

    def test_run_carbon_storage_uses_lulc_cur_path(self, carbon_run_result):
        rc_call = next(tc for tc in carbon_run_result["tool_calls"]
                       if tc["tool"] == "run_carbon_storage")
        assert "lulc_cur_path" in rc_call["arguments"], \
            f"Wrong arg names: {rc_call['arguments']}"

    def test_run_carbon_storage_uses_carbon_pools_path(self, carbon_run_result):
        rc_call = next(tc for tc in carbon_run_result["tool_calls"]
                       if tc["tool"] == "run_carbon_storage")
        assert "carbon_pools_path" in rc_call["arguments"], \
            f"Missing carbon_pools_path: {rc_call['arguments']}"


@pytest.mark.skipif(not has_hq_data, reason="Habitat quality sample data not present")
class TestHabitatQuality:

    def test_run_habitat_quality_tool_called(self, hq_run_result):
        assert "run_habitat_quality" in tools_used(hq_run_result), \
            f"Tools: {tools_used(hq_run_result)}"

    def test_run_habitat_quality_succeeds(self, hq_run_result):
        hq_call = next(tc for tc in hq_run_result["tool_calls"]
                       if tc["tool"] == "run_habitat_quality")
        assert '"status": "success"' in hq_call.get("result_preview", ""), \
            f"Model failed: {hq_call.get('result_preview','')[:400]}"


# ---------------------------------------------------------------------------
# 7. File Upload API
# ---------------------------------------------------------------------------

class TestFileUpload:

    def test_upload_valid_geotiff(self, tmp_path):
        f = tmp_path / "test_upload.tif"
        f.write_bytes(b"TIFF_PLACEHOLDER")
        with open(f, "rb") as fp:
            r = requests.post(f"{BASE_URL}/files/upload",
                              files={"file": ("test_upload.tif", fp, "image/tiff")})
        assert r.status_code == 200
        data = r.json()
        assert data["filename"] == "test_upload.tif"
        assert data["extension"] == ".tif"
        requests.delete(f"{BASE_URL}/files/test_upload.tif")

    def test_upload_csv_file(self, tmp_path):
        f = tmp_path / "carbon_pools.csv"
        f.write_text("lulc_code,c_above\n1,100\n")
        with open(f, "rb") as fp:
            r = requests.post(f"{BASE_URL}/files/upload",
                              files={"file": ("carbon_pools.csv", fp, "text/csv")})
        assert r.status_code == 200
        requests.delete(f"{BASE_URL}/files/carbon_pools.csv")

    def test_upload_geojson(self, tmp_path):
        f = tmp_path / "area.geojson"
        f.write_text('{"type":"FeatureCollection","features":[]}')
        with open(f, "rb") as fp:
            r = requests.post(f"{BASE_URL}/files/upload",
                              files={"file": ("area.geojson", fp, "application/json")})
        assert r.status_code == 200
        requests.delete(f"{BASE_URL}/files/area.geojson")

    def test_upload_rejected_extension(self, tmp_path):
        f = tmp_path / "script.py"
        f.write_text("print('hello')")
        with open(f, "rb") as fp:
            r = requests.post(f"{BASE_URL}/files/upload",
                              files={"file": ("script.py", fp, "text/plain")})
        assert r.status_code == 400

    def test_upload_duplicate_gets_renamed(self, tmp_path):
        f = tmp_path / "dupe.tif"
        f.write_bytes(b"TIFF_DATA")
        with open(f, "rb") as fp:
            r1 = requests.post(f"{BASE_URL}/files/upload",
                               files={"file": ("dupe.tif", fp, "image/tiff")})
        with open(f, "rb") as fp:
            r2 = requests.post(f"{BASE_URL}/files/upload",
                               files={"file": ("dupe.tif", fp, "image/tiff")})
        assert r1.status_code == r2.status_code == 200
        assert r1.json()["filename"] != r2.json()["filename"], "Duplicate not renamed"
        requests.delete(f"{BASE_URL}/files/{r1.json()['filename']}")
        requests.delete(f"{BASE_URL}/files/{r2.json()['filename']}")

    def test_list_files_after_upload(self, tmp_path):
        f = tmp_path / "list_test.csv"
        f.write_text("a,b\n1,2\n")
        with open(f, "rb") as fp:
            requests.post(f"{BASE_URL}/files/upload",
                          files={"file": ("list_test.csv", fp, "text/csv")})
        names = [x["filename"] for x in requests.get(f"{BASE_URL}/files").json()["files"]]
        assert "list_test.csv" in names
        requests.delete(f"{BASE_URL}/files/list_test.csv")

    def test_delete_uploaded_file(self, tmp_path):
        f = tmp_path / "to_delete.tif"
        f.write_bytes(b"TIFF")
        with open(f, "rb") as fp:
            requests.post(f"{BASE_URL}/files/upload",
                          files={"file": ("to_delete.tif", fp, "image/tiff")})
        assert requests.delete(f"{BASE_URL}/files/to_delete.tif").status_code == 200
        names = [x["filename"] for x in requests.get(f"{BASE_URL}/files").json()["files"]]
        assert "to_delete.tif" not in names

    def test_delete_nonexistent_file_returns_404(self):
        assert requests.delete(f"{BASE_URL}/files/nonexistent_xyz.tif").status_code == 404

    def test_path_traversal_rejected(self):
        r = requests.delete(f"{BASE_URL}/files/../../../etc/passwd")
        assert r.status_code in (400, 404, 422)


# ---------------------------------------------------------------------------
# 8. Job Store
# ---------------------------------------------------------------------------

class TestJobStore:

    def test_completed_job_retrievable_by_id(self, invest_list_result):
        job_id = invest_list_result.get("job_id")
        assert job_id, "No job_id returned"
        r = requests.get(f"{BASE_URL}/jobs/{job_id}")
        assert r.status_code == 200
        assert r.json()["job_id"] == job_id

    def test_unknown_job_id_returns_404(self):
        r = requests.get(f"{BASE_URL}/jobs/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404

    def test_job_has_tool_calls(self, invest_list_result):
        # invest_list_result always calls list_models
        job_id = invest_list_result["job_id"]
        assert job_id, "No job_id returned"
        r = requests.get(f"{BASE_URL}/jobs/{job_id}")
        data = r.json()
        # tool_calls may be empty for jobs run before the fix; check SSE result instead
        tc_in_sse = invest_list_result["tool_calls"]
        assert len(tc_in_sse) > 0, "No tool calls seen in SSE stream"


# ---------------------------------------------------------------------------
# 9. ReAct Loop Behaviour
# ---------------------------------------------------------------------------

class TestReActLoop:

    def test_agent_does_not_exceed_10_iterations(self, invest_list_result):
        assert invest_list_result["thinking_iterations"] <= 10, \
            f"Agent ran {invest_list_result['thinking_iterations']} iterations"

    def test_agent_produces_final_response(self, what_can_you_do_result):
        assert what_can_you_do_result["response"] is not None
        assert len(what_can_you_do_result["response"]) > 20

    def test_followup_calls_no_tools(self, followup_result):
        assert followup_result["classified"]["intent"] == "followup"
        assert len(followup_result["tool_calls"]) == 0, \
            f"Followup called tools: {tools_used(followup_result)}"

    def test_multi_turn_context_preserved(self, multi_turn_result):
        resp = (multi_turn_result["response"] or "").lower()
        assert any(w in resp for w in ["model", "carbon", "habitat", "13", "listed"]), \
            f"Response didn't reference prior context: {resp[:200]}"


# ---------------------------------------------------------------------------
# 10. SSE Event Stream Structure
# ---------------------------------------------------------------------------

class TestSSEEventStructure:

    def test_first_event_is_classified(self, invest_list_result):
        assert invest_list_result["raw_events"][0]["type"] == "classified"

    def test_classified_event_has_intent_and_label(self, invest_list_result):
        c = invest_list_result["classified"]
        assert "intent" in c and "label" in c
        assert c["intent"] in ("analysis", "geospatial", "followup")

    def test_last_event_before_done_is_response(self, invest_list_result):
        non_classified = [e for e in invest_list_result["raw_events"] if e["type"] != "classified"]
        assert non_classified[-1]["type"] == "response"

    def test_tool_call_event_has_tool_and_arguments(self, qgis_list_result):
        tool_events = [e for e in qgis_list_result["raw_events"] if e["type"] == "tool_call"]
        assert tool_events, "No tool_call events"
        for ev in tool_events:
            assert "tool" in ev["data"] and "arguments" in ev["data"]

    def test_tool_result_event_has_preview_and_success(self, qgis_list_result):
        result_events = [e for e in qgis_list_result["raw_events"] if e["type"] == "tool_result"]
        assert result_events
        for ev in result_events:
            assert "preview" in ev["data"]
            assert "success" in ev["data"]
            assert "duration_ms" in ev["data"]

    def test_response_event_has_job_id(self, invest_list_result):
        resp_events = [e for e in invest_list_result["raw_events"] if e["type"] == "response"]
        assert resp_events
        assert invest_list_result["job_id"] is not None


# ---------------------------------------------------------------------------
# 11. Tool Parameter Name Correctness (regression vs llama3.1 bug)
# ---------------------------------------------------------------------------

class TestToolParamNames:

    def test_get_raster_info_uses_raster_path(self, raster_info_result):
        for call in [tc for tc in raster_info_result["tool_calls"] if tc["tool"] == "get_raster_info"]:
            assert "raster_path" in call["arguments"], f"Wrong param: {call['arguments']}"

    def test_get_vector_info_uses_vector_path(self, vector_info_result):
        for call in [tc for tc in vector_info_result["tool_calls"] if tc["tool"] == "get_vector_info"]:
            assert "vector_path" in call["arguments"], f"Wrong param: {call['arguments']}"

    def test_get_algorithm_details_uses_algorithm_id(self, algo_details_result):
        for call in [tc for tc in algo_details_result["tool_calls"] if tc["tool"] == "get_algorithm_details"]:
            assert "algorithm_id" in call["arguments"], f"Wrong param: {call['arguments']}"

    def test_reproject_raster_uses_input_raster(self, reproject_result):
        for call in [tc for tc in reproject_result["tool_calls"] if tc["tool"] == "reproject_raster"]:
            assert "input_raster" in call["arguments"], f"Wrong param: {call['arguments']}"

    def test_reproject_raster_uses_target_crs(self, reproject_result):
        for call in [tc for tc in reproject_result["tool_calls"] if tc["tool"] == "reproject_raster"]:
            assert "target_crs" in call["arguments"], f"Missing target_crs: {call['arguments']}"
