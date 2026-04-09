"""
Telecoupling AI - Backend test to verify environment setup.
"""

import os
import pytest

# Ensure PROJ database is findable
os.environ.setdefault(
    "PROJ_DATA",
    os.path.join(os.environ.get("CONDA_PREFIX", ""), "share", "proj"),
)
os.environ.setdefault("PROJ_LIB", os.environ["PROJ_DATA"])


def test_invest_import():
    """Verify natcap.invest can be imported."""
    from osgeo import gdal
    gdal.UseExceptions()
    import natcap.invest
    assert hasattr(natcap.invest, "__version__")


def test_invest_models_importable():
    """Verify all 13 InVEST models can be imported."""
    from osgeo import gdal
    gdal.UseExceptions()

    models = [
        "natcap.invest.coastal_blue_carbon.coastal_blue_carbon",
        "natcap.invest.habitat_quality",
        "natcap.invest.sdr.sdr",
        "natcap.invest.ndr.ndr",
        "natcap.invest.seasonal_water_yield.seasonal_water_yield",
        "natcap.invest.annual_water_yield",
        "natcap.invest.forest_carbon_edge_effect",
        "natcap.invest.carbon",
        "natcap.invest.crop_production_percentile",
        "natcap.invest.crop_production_regression",
        "natcap.invest.pollination",
        "natcap.invest.hra",
        "natcap.invest.recreation.recmodel_client",
    ]
    import importlib
    for model in models:
        mod = importlib.import_module(model)
        assert mod is not None, f"Failed to import {model}"


def test_mcp_import():
    """Verify MCP SDK can be imported."""
    from mcp.server.fastmcp import FastMCP
    assert FastMCP is not None


def test_google_genai_import():
    """Verify Google GenAI SDK can be imported."""
    import google.genai
    assert google.genai is not None


def test_fastapi_import():
    """Verify FastAPI can be imported."""
    from fastapi import FastAPI
    app = FastAPI()
    assert app is not None


def test_geospatial_imports():
    """Verify geospatial libraries can be imported."""
    import rasterio
    import geopandas
    import fiona
    import shapely
    assert all([rasterio, geopandas, fiona, shapely])


def test_config_loads():
    """Verify application config loads without error."""
    from app.core.config import Settings
    s = Settings()
    assert s.gemini_model == "gemini-2.0-flash"
    assert s.invest_mcp_port == 54320
    assert s.qgis_mcp_port == 54321


def test_backend_app_creates():
    """Verify FastAPI app can be created."""
    from app.main import app
    assert app.title == "Telecoupling AI"
