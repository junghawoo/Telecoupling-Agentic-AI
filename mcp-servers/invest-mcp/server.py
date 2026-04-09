"""
Telecoupling AI - InVEST MCP Server

Exposes all 13 NatCap InVEST environmental models as MCP tools.
Each model is a callable tool with typed parameters that runs the
actual InVEST model and returns structured results with output file
paths and raster statistics.

Models:
  1. Coastal Blue Carbon
  2. Habitat Quality
  3. Sediment Delivery Ratio (SDR)
  4. Nutrient Delivery Ratio (NDR)
  5. Seasonal Water Yield
  6. Annual Water Yield
  7. Forest Carbon Edge Effect
  8. Carbon Storage & Sequestration
  9. Crop Production (Percentile)
 10. Crop Production (Regression)
 11. Pollination
 12. Habitat Risk Assessment (HRA)
 13. Recreation (Visitation Rate)
"""

import json
import logging
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)

# Ensure PROJ/GDAL find the correct database.
# CONDA_PREFIX may point to the base env rather than the active telecoupling env,
# so derive the prefix from the running Python executable instead.
import sys as _sys
_env_prefix = str(Path(_sys.executable).parent.parent)  # .../envs/telecoupling
os.environ["PROJ_DATA"] = os.path.join(_env_prefix, "share", "proj")
os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"]
os.environ["GDAL_DATA"] = os.path.join(_env_prefix, "share", "gdal")

from osgeo import gdal  # noqa: E402

gdal.UseExceptions()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("invest-mcp")

# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------
from utils import clean_optional, ensure_workspace, run_invest_model  # noqa: E402

OUTPUT_DIR = os.path.abspath(os.getenv("INVEST_OUTPUT_DIR", "./data/outputs"))

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "InVEST MCP Server",
    instructions="NatCap InVEST 3.14 environmental models exposed as MCP tools",
)


# ========================================================================
# 0a. list_sample_data  (data discovery tool)
# ========================================================================
@mcp.tool()
def list_sample_data() -> str:
    """List all available sample input data files grouped by model.

    Call this BEFORE running any model to get exact file paths for required
    inputs. Returns absolute paths that can be passed directly to model tools.
    """
    sample_root = Path(os.path.abspath(
        os.getenv("INVEST_SAMPLE_DATA_DIR", "./data/sample-inputs")
    ))
    result: dict[str, list[str]] = {}
    if sample_root.exists():
        for model_dir in sorted(sample_root.iterdir()):
            if model_dir.is_dir():
                files = []
                for f in sorted(model_dir.rglob("*")):
                    if f.is_file():
                        files.append(str(f))
                result[model_dir.name] = files
    return json.dumps(result, indent=2)


# ========================================================================
# 0b. get_sample_args  (model argument helper)
# ========================================================================
@mcp.tool()
def get_sample_args(model_name: str) -> str:
    """Return a ready-to-use argument dict for a specific model using sample data.

    Call this to get the exact parameter names and file paths you should pass
    to the corresponding run_* tool. The returned JSON can be used directly
    as the arguments for the model tool call.

    Args:
        model_name: Name of the model (e.g. "carbon_storage", "habitat_quality")
    """
    sample_root = Path(os.path.abspath(
        os.getenv("INVEST_SAMPLE_DATA_DIR", "./data/sample-inputs")
    ))
    hq_dir = sample_root / "HabitatQuality"
    cs_dir = sample_root / "CarbonStorage"
    cbc_dir = sample_root / "CoastalBlueCarbon"

    # Build an absolute-path snapshots CSV for Coastal Blue Carbon so InVEST
    # can resolve the raster files regardless of working directory.
    cbc_snapshots_abs = str(cbc_dir / "inputs" / "snapshots_abs.csv")
    if not Path(cbc_snapshots_abs).exists():
        try:
            import csv
            rows = [["snapshot_year", "raster_path"]]
            for year, fname in [("2010", "GBJC_2010_mean_Resample.tif"),
                                 ("2030", "GBJC_2030_mean_Resample.tif"),
                                 ("2050", "GBJC_2050_mean_Resample.tif")]:
                rows.append([year, str(cbc_dir / "inputs" / fname)])
            with open(cbc_snapshots_abs, "w", newline="") as f:
                csv.writer(f).writerows(rows)
        except Exception:
            cbc_snapshots_abs = str(cbc_dir / "inputs" / "snapshots.csv")

    awy_dir  = sample_root / "AnnualWaterYield"
    ndr_dir  = sample_root / "NDR"
    sdr_dir  = sample_root / "SDR"
    swy_dir  = sample_root / "SeasonalWaterYield"
    pol_dir  = sample_root / "Pollination"
    fce_dir  = sample_root / "ForestCarbonEdge"

    templates: dict[str, dict] = {
        "carbon_storage": {
            "lulc_cur_path":     str(cs_dir / "lulc_current_willamette.tif"),
            "carbon_pools_path": str(cs_dir / "carbon_pools_willamette.csv"),
        },
        "habitat_quality": {
            "lulc_cur_path":          str(hq_dir / "lulc_current_willamette.tif"),
            "lulc_fut_path":          str(hq_dir / "lulc_future_willamette.tif"),
            "threats_table_path":     str(hq_dir / "threats_willamette.csv"),
            "sensitivity_table_path": str(hq_dir / "sensitivity_willamette.csv"),
            "access_vector_path":     str(hq_dir / "accessibility_willamette.shp"),
            "half_saturation_constant": 0.5,
        },
        "coastal_blue_carbon": {
            "landcover_snapshot_csv":     cbc_snapshots_abs,
            "biophysical_table_path":     str(cbc_dir / "outputs_preprocessor" / "biophysical_table_sample.csv"),
            "landcover_transitions_table": str(cbc_dir / "outputs_preprocessor" / "transitions_sample.csv"),
            "analysis_year":              2060,
            "do_economic_analysis":       True,
            "use_price_table":            True,
            "price_table_path":           str(cbc_dir / "inputs" / "Price_table_SCC_5.csv"),
            "discount_rate":              6.0,
        },
        "annual_water_yield": {
            "lulc_path":                    str(awy_dir / "land_use_gura.tif"),
            "biophysical_table_path":       str(awy_dir / "biophysical_table_gura.csv"),
            "eto_path":                     str(awy_dir / "reference_ET_gura.tif"),
            "precipitation_path":           str(awy_dir / "precipitation_gura.tif"),
            "depth_to_root_rest_layer_path": str(awy_dir / "depth_to_root_restricting_layer_gura.tif"),
            "pawc_path":                    str(awy_dir / "plant_available_water_fraction_gura.tif"),
            "watersheds_path":              str(awy_dir / "watershed_gura.shp"),
            "sub_watersheds_path":          str(awy_dir / "subwatersheds_gura.shp"),
            "seasonality_constant":         5,
        },
        "nutrient_delivery_ratio": {
            "dem_path":               str(ndr_dir / "DEM_gura.tif"),
            "lulc_path":              str(ndr_dir / "land_use_gura.tif"),
            "runoff_proxy_path":      str(ndr_dir / "precipitation_gura.tif"),
            "biophysical_table_path": str(ndr_dir / "biophysical_table_gura.csv"),
            "watersheds_path":        str(ndr_dir / "watershed_gura.shp"),
            "calc_n":                 True,
            "calc_p":                 True,
            "threshold_flow_accumulation": 1000,
            "k_param":                2.0,
            "subsurface_critical_length_n": 200,
            "subsurface_eff_n":       0.8,
        },
        "sediment_delivery_ratio": {
            "dem_path":               str(sdr_dir / "DEM_gura.tif"),
            "lulc_path":              str(sdr_dir / "land_use_gura.tif"),
            "erodibility_path":       str(sdr_dir / "erodibility_gura.tif"),
            "erosivity_path":         str(sdr_dir / "erosivity_gura.tif"),
            "biophysical_table_path": str(sdr_dir / "biophysical_table_Gura.csv"),
            "watersheds_path":        str(sdr_dir / "watershed_gura.shp"),
            "threshold_flow_accumulation": 1000,
            "k_param":                2.0,
            "ic_0_param":             0.5,
            "sdr_max":                0.8,
            "l_max":                  122.0,
        },
        "seasonal_water_yield": {
            "lulc_raster_path":       str(swy_dir / "land_use_gura.tif"),
            "dem_raster_path":        str(swy_dir / "DEM_gura.tif"),
            "soil_group_path":        str(swy_dir / "soil_group_gura.tif"),
            "aoi_path":               str(swy_dir / "watershed_gura.shp"),
            "biophysical_table_path": str(swy_dir / "biophysical_table_gura_SWY.csv"),
            "rain_events_table_path": str(swy_dir / "rain_events_gura.csv"),
            "et0_raster_table":       str(swy_dir / "et0_raster_table_gura.csv"),
            "precip_raster_table":    str(swy_dir / "precip_raster_table_gura.csv"),
            "threshold_flow_accumulation": 1000,
            "alpha_m":                "1/12",
            "beta_i":                 1.0,
            "gamma":                  1.0,
            "monthly_alpha":          False,
            "user_defined_local_recharge": False,
            "user_defined_climate_zones": False,
        },
        "pollination": {
            "landcover_raster_path":          str(pol_dir / "landcover.tif"),
            "landcover_biophysical_table_path": str(pol_dir / "landcover_biophysical_table.csv"),
            "guild_table_path":               str(pol_dir / "guild_table.csv"),
            "farm_vector_path":               str(pol_dir / "farms.shp"),
        },
        "forest_carbon_edge_effect": {
            "lulc_raster_path":       str(fce_dir / "forest_carbon_edge_lulc_demo.tif"),
            "biophysical_table_path": str(fce_dir / "forest_edge_carbon_lu_table.csv"),
            "aoi_vector_path":        str(fce_dir / "forest_carbon_edge_demo_aoi.shp"),
            "tropical_forest_edge_carbon_model_vector_path":
                str(fce_dir / "core_data" / "forest_carbon_edge_regression_model_parameters.shp"),
            "n_nearest_model_points":        10,
            "biomass_to_carbon_conversion_factor": 0.47,
            "pools_to_calculate":            "all",
            "compute_forest_edge_effects":   True,
        },
    }

    key = model_name.lower().replace(" ", "_").replace("-", "_")
    if key in templates:
        return json.dumps({
            "model": key,
            "tool_to_call": f"run_{key}",
            "arguments": templates[key],
            "note": "Pass these arguments directly to the tool. Add workspace_dir if desired.",
        }, indent=2)
    else:
        available = sorted(templates.keys())
        return json.dumps({
            "error": f"No sample template for '{model_name}'",
            "available_templates": available,
            "tip": "Call list_sample_data to see all available files.",
        }, indent=2)


# ========================================================================
# 0c. list_models  (discovery tool)
# ========================================================================
@mcp.tool()
def list_models() -> str:
    """List all 13 available InVEST models with descriptions.

    Call this first to discover which environmental models are available
    and understand what each one does before running a specific model.
    """
    models = {
        "coastal_blue_carbon": "Estimates carbon sequestration in coastal ecosystems (mangroves, seagrass, marshes) based on land cover transitions over time",
        "habitat_quality": "Assesses habitat quality and degradation based on land use/land cover threats and habitat sensitivity",
        "sediment_delivery_ratio": "Models overland sediment generation (USLE) and delivery to streams based on land use, topography, and soil erodibility",
        "nutrient_delivery_ratio": "Models nitrogen/phosphorus loading and delivery to streams from land use and biophysical properties",
        "seasonal_water_yield": "Estimates seasonal water yield partitioned into quickflow and baseflow components",
        "annual_water_yield": "Estimates average annual water yield from a watershed using the Budyko curve",
        "forest_carbon_edge_effect": "Maps aboveground carbon storage accounting for tropical forest edge degradation effects",
        "carbon_storage": "Estimates carbon stored and sequestered across land cover types using carbon pool values",
        "crop_production_percentile": "Estimates crop production using observed percentile-based yield datasets",
        "crop_production_regression": "Estimates crop production using regression models based on fertilizer application rates",
        "pollination": "Models wild pollinator abundance and their contributions to crop pollination",
        "habitat_risk_assessment": "Assesses cumulative risk to habitats from human activities (stressors) using exposure-consequence framework",
        "recreation": "Estimates recreation visitation rates based on natural features and predictors",
    }
    return json.dumps(models, indent=2)


# ========================================================================
# 1. Coastal Blue Carbon
# ========================================================================
@mcp.tool()
def run_coastal_blue_carbon(
    landcover_snapshot_csv: str,
    biophysical_table_path: str,
    landcover_transitions_table: str,
    workspace_dir: str = "",
    analysis_year: int = 0,
    do_economic_analysis: bool = False,
    use_price_table: bool = False,
    price: float = 0.0,
    inflation_rate: float = 0.0,
    discount_rate: float = 0.0,
    price_table_path: str = "",
    results_suffix: str = "",
) -> str:
    """Run the InVEST Coastal Blue Carbon model.

    Estimates carbon sequestration and emissions from coastal ecosystems
    (mangroves, seagrass, salt marshes) based on land cover transitions.

    Args:
        landcover_snapshot_csv: Path to CSV mapping snapshot years to LULC rasters (columns: snapshot_year, raster_path)
        biophysical_table_path: Path to biophysical table CSV with carbon pool values per LULC class
        landcover_transitions_table: Path to transition matrix CSV defining disturbance types between LULC transitions
        workspace_dir: Output directory (auto-created if empty)
        analysis_year: Year to extend analysis beyond last snapshot (0 = disabled)
        do_economic_analysis: Whether to run net present value analysis
        use_price_table: Use yearly price table instead of fixed price + inflation
        price: Price of CO2E at baseline year (currency/Mg)
        inflation_rate: Annual increase in CO2E price (percent)
        discount_rate: Annual discount rate on carbon price (percent)
        price_table_path: Path to yearly price table CSV (if use_price_table=True)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.coastal_blue_carbon.coastal_blue_carbon as cbc

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "coastal_blue_carbon"))
    args = {
        "landcover_snapshot_csv": landcover_snapshot_csv,
        "biophysical_table_path": biophysical_table_path,
        "landcover_transitions_table": landcover_transitions_table,
        "workspace_dir": ws,
        "results_suffix": results_suffix,
    }
    if analysis_year > 0:
        args["analysis_year"] = analysis_year
    if do_economic_analysis:
        args["do_economic_analysis"] = True
        args["discount_rate"] = discount_rate
        if use_price_table:
            args["use_price_table"] = True
            args["price_table_path"] = price_table_path
        else:
            args["use_price_table"] = False
            args["price"] = price
            args["inflation_rate"] = inflation_rate

    return run_invest_model("Coastal Blue Carbon", cbc, args, ws)


# ========================================================================
# 2. Habitat Quality
# ========================================================================
@mcp.tool()
def run_habitat_quality(
    lulc_cur_path: str,
    threats_table_path: str,
    sensitivity_table_path: str,
    half_saturation_constant: float,
    workspace_dir: str = "",
    lulc_fut_path: str = "",
    lulc_bas_path: str = "",
    access_vector_path: str = "",
    results_suffix: str = "",
) -> str:
    """Run the InVEST Habitat Quality model.

    Maps habitat quality across a landscape based on threats to habitat
    from human activities. Produces habitat quality and degradation rasters.

    Args:
        lulc_cur_path: Path to current land use/land cover raster
        threats_table_path: Path to threats CSV (columns: THREAT, MAX_DIST, WEIGHT, DECAY, CUR_PATH, and optionally FUT_PATH, BAS_PATH)
        sensitivity_table_path: Path to sensitivity CSV mapping LULC classes to habitat suitability and threat sensitivities
        half_saturation_constant: Half-saturation constant for quality calculation (typically 0.5)
        workspace_dir: Output directory
        lulc_fut_path: Path to future LULC raster (optional, for scenario comparison)
        lulc_bas_path: Path to baseline LULC raster (optional, for comparing with current)
        access_vector_path: Path to access shapefile defining areas with reduced threat (optional)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.habitat_quality

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "habitat_quality"))
    args = {
        "lulc_cur_path": lulc_cur_path,
        "threats_table_path": threats_table_path,
        "sensitivity_table_path": sensitivity_table_path,
        "half_saturation_constant": half_saturation_constant,
        "workspace_dir": ws,
        "results_suffix": results_suffix,
    }
    if clean_optional(lulc_fut_path):
        args["lulc_fut_path"] = lulc_fut_path
    if clean_optional(lulc_bas_path):
        args["lulc_bas_path"] = lulc_bas_path
    if clean_optional(access_vector_path):
        args["access_vector_path"] = access_vector_path

    return run_invest_model("Habitat Quality", natcap.invest.habitat_quality, args, ws)


# ========================================================================
# 3. Sediment Delivery Ratio (SDR)
# ========================================================================
@mcp.tool()
def run_sediment_delivery_ratio(
    biophysical_table_path: str,
    dem_path: str,
    erodibility_path: str,
    erosivity_path: str,
    lulc_path: str,
    threshold_flow_accumulation: int,
    watersheds_path: str,
    workspace_dir: str = "",
    ic_0_param: float = 0.5,
    k_param: float = 2.0,
    sdr_max: float = 0.8,
    l_max: float = 122.0,
    drainage_path: str = "",
    results_suffix: str = "",
) -> str:
    """Run the InVEST Sediment Delivery Ratio (SDR) model.

    Models overland sediment generation via USLE and delivery to streams.
    Outputs include RKLS, USLE, sediment export, and retention rasters.

    Args:
        biophysical_table_path: Path to biophysical table CSV with C and P factors per LULC class
        dem_path: Path to Digital Elevation Model raster
        erodibility_path: Path to soil erodibility (K factor) raster
        erosivity_path: Path to rainfall erosivity (R factor) raster
        lulc_path: Path to land use/land cover raster
        threshold_flow_accumulation: Flow accumulation threshold for stream delineation
        watersheds_path: Path to watersheds vector (shapefile/gpkg)
        workspace_dir: Output directory
        ic_0_param: IC0 calibration parameter (default 0.5)
        k_param: k calibration parameter (default 2.0)
        sdr_max: Maximum SDR value (default 0.8)
        l_max: Maximum L factor value (default 122.0)
        drainage_path: Path to drainage raster (optional)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.sdr.sdr

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "sdr"))
    args = {
        "biophysical_table_path": biophysical_table_path,
        "dem_path": dem_path,
        "erodibility_path": erodibility_path,
        "erosivity_path": erosivity_path,
        "lulc_path": lulc_path,
        "threshold_flow_accumulation": threshold_flow_accumulation,
        "watersheds_path": watersheds_path,
        "workspace_dir": ws,
        "ic_0_param": ic_0_param,
        "k_param": k_param,
        "sdr_max": sdr_max,
        "l_max": l_max,
        "results_suffix": results_suffix,
    }
    if clean_optional(drainage_path):
        args["drainage_path"] = drainage_path

    return run_invest_model("Sediment Delivery Ratio", natcap.invest.sdr.sdr, args, ws)


# ========================================================================
# 4. Nutrient Delivery Ratio (NDR)
# ========================================================================
@mcp.tool()
def run_nutrient_delivery_ratio(
    biophysical_table_path: str,
    dem_path: str,
    lulc_path: str,
    runoff_proxy_path: str,
    threshold_flow_accumulation: int,
    watersheds_path: str,
    workspace_dir: str = "",
    calc_n: bool = True,
    calc_p: bool = True,
    k_param: float = 2.0,
    subsurface_critical_length_n: float = 150.0,
    subsurface_eff_n: float = 0.4,
    subsurface_critical_length_p: float = 150.0,
    subsurface_eff_p: float = 0.4,
    results_suffix: str = "",
) -> str:
    """Run the InVEST Nutrient Delivery Ratio (NDR) model.

    Models nitrogen and/or phosphorus loading and delivery to streams.
    Outputs include nutrient export rasters and watershed summary statistics.

    Args:
        biophysical_table_path: Path to biophysical table CSV with nutrient loading and retention values
        dem_path: Path to Digital Elevation Model raster
        lulc_path: Path to land use/land cover raster
        runoff_proxy_path: Path to runoff proxy raster (e.g. precipitation)
        threshold_flow_accumulation: Flow accumulation threshold for stream delineation
        watersheds_path: Path to watersheds vector
        workspace_dir: Output directory
        calc_n: Calculate nitrogen export (default True)
        calc_p: Calculate phosphorus export (default True)
        k_param: Calibration parameter k (default 2.0)
        subsurface_critical_length_n: Subsurface critical length for nitrogen (meters)
        subsurface_eff_n: Subsurface maximum retention efficiency for nitrogen (0-1)
        subsurface_critical_length_p: Subsurface critical length for phosphorus (meters)
        subsurface_eff_p: Subsurface maximum retention efficiency for phosphorus (0-1)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.ndr.ndr

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "ndr"))
    args = {
        "biophysical_table_path": biophysical_table_path,
        "dem_path": dem_path,
        "lulc_path": lulc_path,
        "runoff_proxy_path": runoff_proxy_path,
        "threshold_flow_accumulation": threshold_flow_accumulation,
        "watersheds_path": watersheds_path,
        "workspace_dir": ws,
        "calc_n": calc_n,
        "calc_p": calc_p,
        "k_param": k_param,
        "results_suffix": results_suffix,
    }
    if calc_n:
        args["subsurface_critical_length_n"] = subsurface_critical_length_n
        args["subsurface_eff_n"] = subsurface_eff_n
    if calc_p:
        args["subsurface_critical_length_p"] = subsurface_critical_length_p
        args["subsurface_eff_p"] = subsurface_eff_p

    return run_invest_model("Nutrient Delivery Ratio", natcap.invest.ndr.ndr, args, ws)


# ========================================================================
# 5. Seasonal Water Yield
# ========================================================================
@mcp.tool()
def run_seasonal_water_yield(
    aoi_path: str,
    biophysical_table_path: str,
    dem_raster_path: str,
    et0_dir: str,
    lulc_raster_path: str,
    precip_dir: str,
    rain_events_table_path: str,
    soil_group_path: str,
    threshold_flow_accumulation: int,
    workspace_dir: str = "",
    alpha_m: float = 0.08333,
    beta_i: float = 1.0,
    gamma: float = 1.0,
    monthly_alpha: bool = False,
    monthly_alpha_path: str = "",
    user_defined_climate_zones: bool = False,
    climate_zone_raster_path: str = "",
    climate_zone_table_path: str = "",
    user_defined_local_recharge: bool = False,
    l_path: str = "",
    results_suffix: str = "",
) -> str:
    """Run the InVEST Seasonal Water Yield model.

    Estimates seasonal water yield partitioned into quickflow and baseflow.
    Requires monthly precipitation and ET0 raster directories.

    Args:
        aoi_path: Path to area of interest vector
        biophysical_table_path: Path to biophysical table CSV with curve numbers and Kc values
        dem_raster_path: Path to Digital Elevation Model raster
        et0_dir: Directory containing 12 monthly reference ET rasters
        lulc_raster_path: Path to land use/land cover raster
        precip_dir: Directory containing 12 monthly precipitation rasters
        rain_events_table_path: Path to rain events table CSV
        soil_group_path: Path to soil hydrologic group raster
        threshold_flow_accumulation: Flow accumulation threshold for streams
        workspace_dir: Output directory
        alpha_m: Fraction of upslope annual available recharge (default 1/12)
        beta_i: Fraction of subsurface recharge available to downslope (default 1.0)
        gamma: Fraction of pixel recharge available to stream (default 1.0)
        monthly_alpha: Use monthly alpha values from table (default False)
        monthly_alpha_path: Path to monthly alpha CSV (if monthly_alpha=True)
        user_defined_climate_zones: Use custom climate zones (default False)
        climate_zone_raster_path: Path to climate zone raster (if user_defined)
        climate_zone_table_path: Path to climate zone table (if user_defined)
        user_defined_local_recharge: Use user-defined local recharge (default False)
        l_path: Path to local recharge raster (if user_defined_local_recharge)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.seasonal_water_yield.seasonal_water_yield

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "seasonal_water_yield"))
    args = {
        "aoi_path": aoi_path,
        "biophysical_table_path": biophysical_table_path,
        "dem_raster_path": dem_raster_path,
        "et0_dir": et0_dir,
        "lulc_raster_path": lulc_raster_path,
        "precip_dir": precip_dir,
        "rain_events_table_path": rain_events_table_path,
        "soil_group_path": soil_group_path,
        "threshold_flow_accumulation": threshold_flow_accumulation,
        "workspace_dir": ws,
        "alpha_m": alpha_m,
        "beta_i": beta_i,
        "gamma": gamma,
        "monthly_alpha": monthly_alpha,
        "user_defined_climate_zones": user_defined_climate_zones,
        "user_defined_local_recharge": user_defined_local_recharge,
        "results_suffix": results_suffix,
    }
    if monthly_alpha and clean_optional(monthly_alpha_path):
        args["monthly_alpha_path"] = monthly_alpha_path
    if user_defined_climate_zones:
        if clean_optional(climate_zone_raster_path):
            args["climate_zone_raster_path"] = climate_zone_raster_path
        if clean_optional(climate_zone_table_path):
            args["climate_zone_table_path"] = climate_zone_table_path
    if user_defined_local_recharge and clean_optional(l_path):
        args["l_path"] = l_path

    return run_invest_model(
        "Seasonal Water Yield",
        natcap.invest.seasonal_water_yield.seasonal_water_yield,
        args,
        ws,
    )


# ========================================================================
# 6. Annual Water Yield
# ========================================================================
@mcp.tool()
def run_annual_water_yield(
    lulc_path: str,
    depth_to_root_rest_layer_path: str,
    precipitation_path: str,
    pawc_path: str,
    eto_path: str,
    watersheds_path: str,
    biophysical_table_path: str,
    seasonality_constant: float,
    workspace_dir: str = "",
    sub_watersheds_path: str = "",
    demand_table_path: str = "",
    valuation_table_path: str = "",
    results_suffix: str = "",
) -> str:
    """Run the InVEST Annual Water Yield model.

    Estimates average annual water yield from a watershed using the Budyko
    curve. Optionally computes water scarcity and valuation.

    Args:
        lulc_path: Path to land use/land cover raster
        depth_to_root_rest_layer_path: Path to root restricting layer depth raster (mm)
        precipitation_path: Path to annual average precipitation raster (mm)
        pawc_path: Path to plant available water content raster (fraction 0-1)
        eto_path: Path to annual reference evapotranspiration raster (mm)
        watersheds_path: Path to watersheds vector
        biophysical_table_path: Path to biophysical table CSV with root depth and Kc per LULC
        seasonality_constant: Zhang seasonality constant (1-30, higher = more seasonal)
        workspace_dir: Output directory
        sub_watersheds_path: Path to sub-watersheds vector (optional)
        demand_table_path: Path to water demand table CSV (optional, for scarcity)
        valuation_table_path: Path to valuation table CSV (optional, for economic value)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.annual_water_yield

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "annual_water_yield"))
    args = {
        "lulc_path": lulc_path,
        "depth_to_root_rest_layer_path": depth_to_root_rest_layer_path,
        "precipitation_path": precipitation_path,
        "pawc_path": pawc_path,
        "eto_path": eto_path,
        "watersheds_path": watersheds_path,
        "biophysical_table_path": biophysical_table_path,
        "seasonality_constant": seasonality_constant,
        "workspace_dir": ws,
        "results_suffix": results_suffix,
    }
    if clean_optional(sub_watersheds_path):
        args["sub_watersheds_path"] = sub_watersheds_path
    if clean_optional(demand_table_path):
        args["demand_table_path"] = demand_table_path
    if clean_optional(valuation_table_path):
        args["valuation_table_path"] = valuation_table_path

    return run_invest_model("Annual Water Yield", natcap.invest.annual_water_yield, args, ws)


# ========================================================================
# 7. Forest Carbon Edge Effect
# ========================================================================
@mcp.tool()
def run_forest_carbon_edge_effect(
    lulc_raster_path: str,
    biophysical_table_path: str,
    pools_to_calculate: str,
    workspace_dir: str = "",
    compute_forest_edge_effects: bool = True,
    tropical_forest_edge_carbon_model_vector_path: str = "",
    n_nearest_model_points: int = 10,
    biomass_to_carbon_conversion_factor: float = 0.47,
    aoi_vector_path: str = "",
    results_suffix: str = "",
) -> str:
    """Run the InVEST Forest Carbon Edge Effect model.

    Maps aboveground carbon storage accounting for forest edge degradation.
    Uses a regression model based on distance to forest edge.

    Args:
        lulc_raster_path: Path to land use/land cover raster
        biophysical_table_path: Path to biophysical table CSV mapping LULC codes to carbon values
        pools_to_calculate: Which carbon pools to compute: "all" or specific pools
        workspace_dir: Output directory
        compute_forest_edge_effects: Whether to apply edge effect regression (default True)
        tropical_forest_edge_carbon_model_vector_path: Path to tropical forest edge carbon model vector (optional)
        n_nearest_model_points: Number of nearest model points for regression (default 10)
        biomass_to_carbon_conversion_factor: Factor to convert biomass to carbon (default 0.47)
        aoi_vector_path: Path to area of interest vector for summary stats (optional)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.forest_carbon_edge_effect

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "forest_carbon_edge"))
    args = {
        "lulc_raster_path": lulc_raster_path,
        "biophysical_table_path": biophysical_table_path,
        "pools_to_calculate": pools_to_calculate,
        "compute_forest_edge_effects": compute_forest_edge_effects,
        "n_nearest_model_points": n_nearest_model_points,
        "biomass_to_carbon_conversion_factor": biomass_to_carbon_conversion_factor,
        "workspace_dir": ws,
        "results_suffix": results_suffix,
    }
    if clean_optional(tropical_forest_edge_carbon_model_vector_path):
        args["tropical_forest_edge_carbon_model_vector_path"] = (
            tropical_forest_edge_carbon_model_vector_path
        )
    if clean_optional(aoi_vector_path):
        args["aoi_vector_path"] = aoi_vector_path

    return run_invest_model(
        "Forest Carbon Edge Effect",
        natcap.invest.forest_carbon_edge_effect,
        args,
        ws,
    )


# ========================================================================
# 8. Carbon Storage & Sequestration
# ========================================================================
@mcp.tool()
def run_carbon_storage(
    lulc_cur_path: str,
    carbon_pools_path: str,
    workspace_dir: str = "",
    calc_sequestration: bool = False,
    lulc_fut_path: str = "",
    do_redd: bool = False,
    lulc_redd_path: str = "",
    lulc_cur_year: int = 0,
    lulc_fut_year: int = 0,
    do_valuation: bool = False,
    price_per_metric_ton_of_c: float = 0.0,
    discount_rate: float = 0.0,
    rate_change: float = 0.0,
    results_suffix: str = "",
) -> str:
    """Run the InVEST Carbon Storage and Sequestration model.

    Estimates carbon stored in four pools (above/below ground, soil, dead)
    based on land cover. Optionally calculates sequestration and economic value.

    Args:
        lulc_cur_path: Path to current land use/land cover raster
        carbon_pools_path: Path to carbon pools CSV (columns: lucode, C_above, C_below, C_soil, C_dead)
        workspace_dir: Output directory
        calc_sequestration: Calculate sequestration between current and future (default False)
        lulc_fut_path: Path to future LULC raster (required if calc_sequestration)
        do_redd: Run REDD scenario analysis (default False)
        lulc_redd_path: Path to REDD policy LULC raster (required if do_redd)
        lulc_cur_year: Year of current LULC (required for sequestration/valuation)
        lulc_fut_year: Year of future LULC (required for sequestration/valuation)
        do_valuation: Run economic valuation (default False)
        price_per_metric_ton_of_c: Price per metric ton of carbon
        discount_rate: Annual discount rate (percent)
        rate_change: Annual rate of change of carbon price (percent)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.carbon

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "carbon_storage"))
    # InVEST carbon uses lulc_bas_path / lulc_alt_path (not lulc_cur / lulc_fut)
    args = {
        "lulc_bas_path": lulc_cur_path,
        "carbon_pools_path": carbon_pools_path,
        "workspace_dir": ws,
        "results_suffix": results_suffix,
    }
    if calc_sequestration and clean_optional(lulc_fut_path):
        args["lulc_alt_path"] = lulc_fut_path
    if do_redd and clean_optional(lulc_redd_path):
        args["lulc_redd_path"] = lulc_redd_path
    if lulc_cur_year > 0:
        args["lulc_bas_year"] = lulc_cur_year
    if lulc_fut_year > 0:
        args["lulc_alt_year"] = lulc_fut_year
    if do_valuation:
        args["do_valuation"] = True
        args["price_per_metric_ton_of_c"] = price_per_metric_ton_of_c
        args["discount_rate"] = discount_rate
        args["rate_change"] = rate_change

    return run_invest_model("Carbon Storage & Sequestration", natcap.invest.carbon, args, ws)


# ========================================================================
# 9. Crop Production (Percentile)
# ========================================================================
@mcp.tool()
def run_crop_production_percentile(
    landcover_raster_path: str,
    landcover_to_crop_table_path: str,
    model_data_path: str,
    workspace_dir: str = "",
    aggregate_polygon_path: str = "",
    results_suffix: str = "",
) -> str:
    """Run the InVEST Crop Production Percentile model.

    Estimates crop yields using globally observed percentile yield datasets.
    Provides 25th, 50th, 75th percentile production estimates.

    Args:
        landcover_raster_path: Path to land cover raster with crop codes
        landcover_to_crop_table_path: Path to CSV mapping LULC codes to crop names
        model_data_path: Path to directory containing InVEST global crop yield datasets
        workspace_dir: Output directory
        aggregate_polygon_path: Path to polygon vector for aggregated summaries (optional)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.crop_production_percentile

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "crop_percentile"))
    args = {
        "landcover_raster_path": landcover_raster_path,
        "landcover_to_crop_table_path": landcover_to_crop_table_path,
        "model_data_path": model_data_path,
        "workspace_dir": ws,
        "results_suffix": results_suffix,
    }
    if clean_optional(aggregate_polygon_path):
        args["aggregate_polygon_path"] = aggregate_polygon_path

    return run_invest_model(
        "Crop Production Percentile",
        natcap.invest.crop_production_percentile,
        args,
        ws,
    )


# ========================================================================
# 10. Crop Production (Regression)
# ========================================================================
@mcp.tool()
def run_crop_production_regression(
    landcover_raster_path: str,
    landcover_to_crop_table_path: str,
    fertilization_rate_table_path: str,
    model_data_path: str,
    workspace_dir: str = "",
    aggregate_polygon_path: str = "",
    results_suffix: str = "",
) -> str:
    """Run the InVEST Crop Production Regression model.

    Estimates crop yields using regression models based on fertilizer
    application rates (nitrogen, phosphorus, potassium).

    Args:
        landcover_raster_path: Path to land cover raster with crop codes
        landcover_to_crop_table_path: Path to CSV mapping LULC codes to crop names
        fertilization_rate_table_path: Path to CSV with fertilization rates (N, P, K) per crop
        model_data_path: Path to directory containing InVEST global crop model datasets
        workspace_dir: Output directory
        aggregate_polygon_path: Path to polygon vector for aggregated summaries (optional)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.crop_production_regression

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "crop_regression"))
    args = {
        "landcover_raster_path": landcover_raster_path,
        "landcover_to_crop_table_path": landcover_to_crop_table_path,
        "fertilization_rate_table_path": fertilization_rate_table_path,
        "model_data_path": model_data_path,
        "workspace_dir": ws,
        "results_suffix": results_suffix,
    }
    if clean_optional(aggregate_polygon_path):
        args["aggregate_polygon_path"] = aggregate_polygon_path

    return run_invest_model(
        "Crop Production Regression",
        natcap.invest.crop_production_regression,
        args,
        ws,
    )


# ========================================================================
# 11. Pollination
# ========================================================================
@mcp.tool()
def run_pollination(
    landcover_raster_path: str,
    guild_table_path: str,
    landcover_biophysical_table_path: str,
    workspace_dir: str = "",
    farm_vector_path: str = "",
    results_suffix: str = "",
) -> str:
    """Run the InVEST Pollination model.

    Models wild pollinator abundance across a landscape and their
    contributions to crop pollination based on nesting and foraging habitat.

    Args:
        landcover_raster_path: Path to land use/land cover raster
        guild_table_path: Path to pollinator guild table CSV (species, nesting, foraging attributes)
        landcover_biophysical_table_path: Path to biophysical table CSV mapping LULC to nesting/foraging suitability
        workspace_dir: Output directory
        farm_vector_path: Path to farm vector with crop info (optional, for on-farm pollination)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.pollination

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "pollination"))
    args = {
        "landcover_raster_path": landcover_raster_path,
        "guild_table_path": guild_table_path,
        "landcover_biophysical_table_path": landcover_biophysical_table_path,
        "workspace_dir": ws,
        "results_suffix": results_suffix,
    }
    if clean_optional(farm_vector_path):
        args["farm_vector_path"] = farm_vector_path

    return run_invest_model("Pollination", natcap.invest.pollination, args, ws)


# ========================================================================
# 12. Habitat Risk Assessment (HRA)
# ========================================================================
@mcp.tool()
def run_habitat_risk_assessment(
    info_table_path: str,
    criteria_table_path: str,
    resolution: int,
    max_rating: int,
    risk_eq: str,
    decay_eq: str,
    workspace_dir: str = "",
    aoi_vector_path: str = "",
    n_overlapping_stressors: int = 1,
    visualize_outputs: bool = True,
    results_suffix: str = "",
) -> str:
    """Run the InVEST Habitat Risk Assessment (HRA) model.

    Assesses cumulative risk to habitats from human activities using an
    exposure-consequence framework. Produces risk classification maps.

    Args:
        info_table_path: Path to habitat-stressor information CSV
        criteria_table_path: Path to criteria scores CSV
        resolution: Analysis resolution in meters
        max_rating: Maximum criteria rating value (e.g. 3)
        risk_eq: Risk equation: "Euclidean" or "Multiplicative"
        decay_eq: Stressor decay equation: "Linear" or "Exponential" or "None"
        workspace_dir: Output directory
        aoi_vector_path: Path to area of interest vector (optional)
        n_overlapping_stressors: Number of overlapping stressors for cumulative risk (default 1)
        visualize_outputs: Generate visualization outputs (default True)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.hra

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "hra"))
    args = {
        "info_table_path": info_table_path,
        "criteria_table_path": criteria_table_path,
        "resolution": resolution,
        "max_rating": max_rating,
        "risk_eq": risk_eq,
        "decay_eq": decay_eq,
        "workspace_dir": ws,
        "n_overlapping_stressors": n_overlapping_stressors,
        "visualize_outputs": visualize_outputs,
        "results_suffix": results_suffix,
    }
    if clean_optional(aoi_vector_path):
        args["aoi_vector_path"] = aoi_vector_path

    return run_invest_model("Habitat Risk Assessment", natcap.invest.hra, args, ws)


# ========================================================================
# 13. Recreation (Visitation Rate)
# ========================================================================
@mcp.tool()
def run_recreation(
    aoi_path: str,
    start_year: str,
    end_year: str,
    workspace_dir: str = "",
    hostname: str = "localhost",
    port: int = 443,
    grid_aoi: bool = True,
    grid_type: str = "hexagon",
    cell_size: float = 7000.0,
    compute_regression: bool = False,
    predictor_table_path: str = "",
    scenario_predictor_table_path: str = "",
    results_suffix: str = "",
) -> str:
    """Run the InVEST Recreation model (Visitation Rate).

    Estimates recreation visitation rates based on natural features.
    Uses photo-user-day data from Flickr as a proxy for visitation.

    NOTE: This model requires network access to the NatCap recreation
    server for photo-user-day data. It may not work in offline environments.

    Args:
        aoi_path: Path to area of interest vector
        start_year: Start year for analysis (e.g. "2010")
        end_year: End year for analysis (e.g. "2020")
        workspace_dir: Output directory
        hostname: Recreation server hostname (default "localhost")
        port: Recreation server port (default 443)
        grid_aoi: Grid the AOI into cells (default True)
        grid_type: Grid cell type: "hexagon" or "square" (default "hexagon")
        cell_size: Grid cell size in meters (default 7000)
        compute_regression: Compute regression with predictors (default False)
        predictor_table_path: Path to predictor table CSV (optional)
        scenario_predictor_table_path: Path to scenario predictor CSV (optional)
        results_suffix: Suffix appended to output filenames
    """
    import natcap.invest.recreation.recmodel_client

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "recreation"))
    args = {
        "aoi_path": aoi_path,
        "start_year": start_year,
        "end_year": end_year,
        "hostname": hostname,
        "port": port,
        "grid_aoi": grid_aoi,
        "grid_type": grid_type,
        "cell_size": cell_size,
        "compute_regression": compute_regression,
        "workspace_dir": ws,
        "results_suffix": results_suffix,
    }
    if compute_regression and clean_optional(predictor_table_path):
        args["predictor_table_path"] = predictor_table_path
    if clean_optional(scenario_predictor_table_path):
        args["scenario_predictor_table_path"] = scenario_predictor_table_path

    return run_invest_model(
        "Recreation (Visitation Rate)",
        natcap.invest.recreation.recmodel_client,
        args,
        ws,
    )


# ========================================================================
# Entry point
# ========================================================================
if __name__ == "__main__":
    port = int(os.getenv("INVEST_MCP_PORT", 54320))
    logger.info(f"Starting InVEST MCP Server on port {port} with 16 tools (13 models + list_models + list_sample_data + get_sample_args)")
    mcp.settings.port = port
    mcp.run(transport="sse")
