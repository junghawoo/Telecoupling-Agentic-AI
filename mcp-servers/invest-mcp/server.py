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
# Self-contained: load .env from THIS directory first.
# Falls back to the repo-root .env (two levels up) without overriding.
_here = Path(__file__).resolve().parent
load_dotenv(_here / ".env")                                     # server-local (highest priority)
load_dotenv(_here.parent.parent / ".env", override=False)       # repo-root fallback

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
# 0d. Coastal Blue Carbon Preprocessor
# ========================================================================
@mcp.tool()
def run_coastal_blue_carbon_preprocessor(
    landcover_snapshot_csv: str,
    lulc_lookup_table_path: str,
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """Run the InVEST Coastal Blue Carbon Preprocessor.

    Generates the biophysical table and land-cover transition matrix that
    the main Coastal Blue Carbon model (run_coastal_blue_carbon) requires.
    Must be run before run_coastal_blue_carbon when starting from raw LULC
    rasters.

    After this tool finishes, open the output transitions_*.csv and fill in
    the transition type for each LULC pair: 'accumulation', 'disturb', or
    'NCC' (no change in carbon).  Then pass the edited file to
    run_coastal_blue_carbon as landcover_transitions_table.

    Args:
        landcover_snapshot_csv: Path to a CSV with columns 'snapshot_year'
            and 'raster_path' mapping each time-step to a LULC raster.
            Raster paths may be absolute or relative to the CSV's directory.
        lulc_lookup_table_path: Path to a CSV mapping LULC codes to class
            names and a boolean is_coastal_blue_carbon_habitat column.
        workspace_dir: Output directory (auto-created if empty).
        results_suffix: Suffix appended to all output filenames.
    """
    import csv as _csv
    import natcap.invest.coastal_blue_carbon.preprocessor

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "cbc_preprocessor"))

    # ── Resolve relative raster paths in the snapshot CSV ────────────────
    # InVEST resolves paths relative to the CWD, not the CSV's directory.
    # We rewrite the CSV with absolute paths so the model always finds the files.
    snapshot_path = Path(landcover_snapshot_csv).resolve()
    snapshot_dir  = snapshot_path.parent
    abs_snapshot  = os.path.join(ws, f"snapshots_abs{results_suffix}.csv")

    with open(snapshot_path, newline="", encoding="utf-8-sig") as f_in, \
         open(abs_snapshot, "w", newline="", encoding="utf-8") as f_out:
        reader = _csv.DictReader(f_in)
        writer = _csv.DictWriter(f_out, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            raster = row.get("raster_path", "").strip()
            if raster and not Path(raster).is_absolute():
                row["raster_path"] = str((snapshot_dir / raster).resolve())
            writer.writerow(row)

    args = {
        "landcover_snapshot_csv": abs_snapshot,
        "lulc_lookup_table_path": lulc_lookup_table_path,
        "workspace_dir":          ws,
        "results_suffix":         results_suffix,
    }
    return run_invest_model(
        "Coastal Blue Carbon Preprocessor",
        natcap.invest.coastal_blue_carbon.preprocessor,
        args,
        ws,
    )


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
# ====================================================================
# Coastal Vulnerability
# (auto-generated from coastal_vulnerability.py by nan_to_mcp.py)
# ⚠ REVIEW: source has conditional param logic — verify args dict below
# ====================================================================
@mcp.tool()
def run_coastal_vulnerability(
    aoi_vector_path: str,
    bathymetry_raster_path: str,
    dem_averaging_radius: int,
    dem_path: str,
    geomorphology_fill_value: int,
    geomorphology_vector_path: str,
    landmass_vector_path: str,
    max_fetch_distance: int,
    model_resolution: int,
    wwiii_vector_path: str,
    habitat_table_path: str = "",
    shelf_contour_vector_path: str = "",
    slr_vector_path: str = "",
    population_raster_path: str = "",
    population_radius: int = 0,
    slr_field: str = "",
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """For points along a coastline, evaluate the relative exposure of points to
    coastal hazards based on up to eight biophysical hazard indices. Also
    quantify the role of habitats in reducing the hazard. Optionally
    summarize the population density in proximity to each shore point.

    Args:
        aoi_vector_path: Path to a polygon vector that is projected in a
            coordinate system with units of meters. The polygon should
            intersect the landmass and the shelf contour line.
        bathymetry_raster_path: Path to a raster representing the depth
            below sea level, in negative meters. Should cover the area
            extending outward from the AOI to the max_fetch_distance.
        dem_averaging_radius: A value >= 0. The radius in meters around
            each shore point in which to compute the average elevation.
        dem_path: Path to a raster representing the elevation on land in
            the region of interest.
        geomorphology_fill_value: A value from 1 to 5 that will be used as
            a geomorphology rank for any points not proximate to the
            geomorphology_vector_path.
        geomorphology_vector_path: Path to a polyline vector that has a
            field called “RANK” with values from 1 to 5 in the attribute
            table.
        landmass_vector_path: Path to a polygon vector representing
            landmasses in the region of interest.
        max_fetch_distance: Maximum distance in meters to extend rays from
            shore points. Points with rays equal to this distance will
            accumulate ocean-driven wave exposure along those rays and
            local-wind-driven wave exposure along the shorter rays.
        model_resolution: Distance in meters. Points are spaced along the
            coastline at intervals of this distance.
        wwiii_vector_path: Path to a point vector containing wind and wave
            information across the region of interest.
        habitat_table_path: Path to a CSV file with the following four
            fields: ‘id’: unique string to represent each habitat; ‘path’:
            absolute or relative path to a polygon vector; ‘rank’: integer
            from 1 to 5 representing the relative protection offered by
            this habitat; ‘protection distance (m)’: integer or float used
            as a search radius around each shore point.
        shelf_contour_vector_path: Path to a polyline vector delineating
            edges of the continental shelf or other bathymetry contour.
        slr_vector_path: Path to point vector containing the field args['slr_field'] .
        population_raster_path: Path a raster with values of total population per pixel.
        population_radius: A value >= 0. The radius in meters around each
            shore point in which to compute the population density.
        slr_field: Name of a field in args['slr_vector_path'] containing numeric values.
        workspace_dir: A path to the directory that will write output and
            other temporary files during calculation.
        results_suffix: Appended to any output filename.
    """
    import natcap.invest.coastal_vulnerability

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "coastal_vulnerability"))
    args = {
        "aoi_vector_path": aoi_vector_path,
        "bathymetry_raster_path": bathymetry_raster_path,
        "dem_averaging_radius": dem_averaging_radius,
        "dem_path": dem_path,
        "geomorphology_fill_value": geomorphology_fill_value,
        "geomorphology_vector_path": geomorphology_vector_path,
        "landmass_vector_path": landmass_vector_path,
        "max_fetch_distance": max_fetch_distance,
        "model_resolution": model_resolution,
        "wwiii_vector_path": wwiii_vector_path,
        "habitat_table_path": habitat_table_path,
        "shelf_contour_vector_path": shelf_contour_vector_path,
        "slr_vector_path": slr_vector_path,
        "population_raster_path": population_raster_path,
        "population_radius": population_radius,
        "slr_field": slr_field,
        "workspace_dir": ws,
        "results_suffix": results_suffix,
    }

    return run_invest_model("Coastal Vulnerability", natcap.invest.coastal_vulnerability, args, ws)




# ========================================================================
# 15. DelineateIt
# ========================================================================
@mcp.tool()
def run_delineateit(
    dem_path: str,
    detect_pour_points: bool = False,
    outlet_vector_path: str = "",
    snap_points: bool = False,
    flow_threshold: int = 1000,
    snap_distance: int = 20,
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """Watershed delineation wrapper around pygeoprocessing routing.

    Delineates watersheds from a DEM by snapping pour points to the nearest
    stream and tracing upstream contributing areas.

    Args:
        dem_path: Path to a GDAL-supported elevation raster. Fill sinks
            before use; consider burning hydrographic features first.
        detect_pour_points: If True, auto-detect pour points from the DEM
            instead of using outlet_vector_path. Default: False.
        outlet_vector_path: Path to outlet points vector. Required when
            detect_pour_points is False.
        snap_points: If True, snap outlet points to the nearest stream pixel
            (requires flow_threshold and snap_distance). Default: False.
        flow_threshold: Minimum upslope cells to define a stream pixel
            (used when snap_points=True). Default: 1000.
        snap_distance: Maximum pixel distance to snap outlet points to a
            stream (used when snap_points=True). Default: 20.
        workspace_dir: Output directory (auto-created if empty).
        results_suffix: Suffix appended to all output filenames.
    """
    import natcap.invest.delineateit.delineateit

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "delineateit"))
    args = {
        "dem_path":            dem_path,
        "detect_pour_points":  detect_pour_points,
        "snap_points":         snap_points,
        "workspace_dir":       ws,
        "results_suffix":      results_suffix,
    }
    if not detect_pour_points and clean_optional(outlet_vector_path):
        args["outlet_vector_path"] = outlet_vector_path
    if snap_points:
        args["flow_threshold"] = flow_threshold
        args["snap_distance"]  = snap_distance

    return run_invest_model("DelineateIt", natcap.invest.delineateit.delineateit, args, ws)


# ========================================================================
# 16. RouteDEM
# ========================================================================
@mcp.tool()
def run_routedem(
    dem_path: str,
    algorithm: str = "D8",
    calculate_flow_direction: bool = True,
    calculate_flow_accumulation: bool = True,
    calculate_stream_threshold: bool = False,
    threshold_flow_accumulation: int = 1000,
    calculate_slope: bool = False,
    calculate_stream_order: bool = False,
    calculate_downstream_distance: bool = False,
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """Exposes pygeoprocessing D8 and MFD routing as an InVEST model.

    Computes hydrological routing outputs from a DEM — flow direction, flow
    accumulation, slope, stream networks, and downstream distance rasters.
    Always fills pits on the input DEM before routing.

    Args:
        dem_path: Path to a digital elevation raster.
        algorithm: Routing algorithm — 'D8' (single direction) or 'MFD'
            (multiple flow direction). Default: 'D8'.
        calculate_flow_direction: If True, compute flow direction raster. Default: True.
        calculate_flow_accumulation: If True, compute flow accumulation raster.
        calculate_stream_threshold: If True, compute stream classification
            raster (requires threshold_flow_accumulation).
        threshold_flow_accumulation: Minimum upslope cells to classify a
            stream pixel (used when calculate_stream_threshold=True). Default: 1000.
        calculate_slope: If True, compute slope raster.
        calculate_stream_order: If True, compute Strahler stream order vector.
        calculate_downstream_distance: If True, compute downstream
            distance-to-stream raster.
        workspace_dir: Output directory (auto-created if empty).
        results_suffix: Suffix appended to all output filenames.
    """
    import natcap.invest.routedem

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "routedem"))
    args = {
        "dem_path":                      dem_path,
        "algorithm":                     algorithm,
        "calculate_flow_direction":      calculate_flow_direction,
        "calculate_flow_accumulation":   calculate_flow_accumulation,
        "calculate_stream_threshold":    calculate_stream_threshold,
        "calculate_slope":               calculate_slope,
        "calculate_stream_order":        calculate_stream_order,
        "calculate_downstream_distance": calculate_downstream_distance,
        "workspace_dir":                 ws,
        "results_suffix":                results_suffix,
    }
    if calculate_stream_threshold:
        args["threshold_flow_accumulation"] = threshold_flow_accumulation

    return run_invest_model("RouteDEM", natcap.invest.routedem, args, ws)


# ========================================================================
# 17. Scenic Quality
# ========================================================================
@mcp.tool()
def run_scenic_quality(
    aoi_path: str,
    structure_path: str,
    dem_path: str,
    refraction: float = 0.13,
    do_valuation: bool = False,
    valuation_function: str = "",
    a_coef: float = 0.0,
    b_coef: float = 0.0,
    max_valuation_radius: float = 0.0,
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """Quantify the visual impact of built structures on scenic quality.

    Runs viewshed analysis across the AOI and optionally computes the
    economic value of view impairment (e.g. from wind turbines or cell towers).

    Args:
        aoi_path: Path to a vector indicating the area of interest.
        structure_path: Path to a point vector with viewpoint features.
            Optional fields: WEIGHT, RADIUS/RADIUS2, HEIGHT.
        dem_path: Path to a digital elevation model raster.
        refraction: Refraction coefficient for earth-curvature correction.
            Default: 0.13.
        do_valuation: If True, compute economic valuation of view impairment.
            Default: False.
        valuation_function: Valuation function type when do_valuation=True —
            'linear', 'logarithmic', or 'exponential'.
        a_coef: Coefficient 'a' in the valuation function.
        b_coef: Coefficient 'b' in the valuation function.
        max_valuation_radius: Beyond this distance (meters) pixel values are
            set to 0. Leave 0 for no limit.
        workspace_dir: Output directory (auto-created if empty).
        results_suffix: Suffix appended to all output filenames.
    """
    import natcap.invest.scenic_quality.scenic_quality

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "scenic_quality"))
    args = {
        "aoi_path":       aoi_path,
        "structure_path": structure_path,
        "dem_path":       dem_path,
        "refraction":     refraction,
        "do_valuation":   do_valuation,
        "workspace_dir":  ws,
        "results_suffix": results_suffix,
    }
    if do_valuation:
        args["valuation_function"] = valuation_function
        args["a_coef"]             = a_coef
        args["b_coef"]             = b_coef
        if max_valuation_radius > 0:
            args["max_valuation_radius"] = max_valuation_radius

    return run_invest_model("Scenic Quality", natcap.invest.scenic_quality.scenic_quality, args, ws)


# ========================================================================
# 18. Scenario Generator — Proximity Based
# ========================================================================
@mcp.tool()
def run_scenario_gen_proximity(
    base_lulc_path: str,
    replacement_lucode: int,
    area_to_convert: float,
    focal_landcover_codes: str,
    convertible_landcover_codes: str,
    convert_nearest_to_edge: bool = True,
    convert_farthest_from_edge: bool = False,
    n_fragmentation_steps: int = 1,
    aoi_path: str = "",
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """Generate a modified LULC scenario by converting pixels nearest or
    farthest from a focal landcover type up to a specified area target.

    Args:
        base_lulc_path: Path to the base land use/land cover raster.
        replacement_lucode: LULC integer code to assign to converted pixels.
        area_to_convert: Maximum area to convert in hectares.
        focal_landcover_codes: Space-separated integer LULC codes defining
            the focal/reference landcover (conversion proximity is measured
            relative to these).
        convertible_landcover_codes: Space-separated integer LULC codes
            eligible for conversion.
        convert_nearest_to_edge: If True, convert pixels nearest to the
            focal landcover edge first. Default: True.
        convert_farthest_from_edge: If True, convert pixels farthest from
            the focal landcover edge first. Default: False.
        n_fragmentation_steps: Number of fragmentation conversion steps. Default: 1.
        aoi_path: Path to AOI shapefile — conversion is clipped to this area. (optional)
        workspace_dir: Output directory (auto-created if empty).
        results_suffix: Suffix appended to all output filenames.
    """
    import natcap.invest.scenario_gen_proximity

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "scenario_gen_proximity"))
    args = {
        "base_lulc_path":              base_lulc_path,
        "replacement_lucode":          replacement_lucode,
        "area_to_convert":             area_to_convert,
        "focal_landcover_codes":       focal_landcover_codes,
        "convertible_landcover_codes": convertible_landcover_codes,
        "convert_nearest_to_edge":     convert_nearest_to_edge,
        "convert_farthest_from_edge":  convert_farthest_from_edge,
        "n_fragmentation_steps":       n_fragmentation_steps,
        "workspace_dir":               ws,
        "results_suffix":              results_suffix,
    }
    if clean_optional(aoi_path):
        args["aoi_path"] = aoi_path

    return run_invest_model(
        "Scenario Generator (Proximity)", natcap.invest.scenario_gen_proximity, args, ws
    )


# ========================================================================
# 19. Urban Cooling
# ========================================================================
@mcp.tool()
def run_urban_cooling(
    lulc_raster_path: str,
    ref_eto_raster_path: str,
    aoi_vector_path: str,
    biophysical_table_path: str,
    green_area_cooling_distance: float,
    t_ref: float,
    uhi_max: float,
    cc_method: str = "factors",
    t_air_average_radius: float = 2000.0,
    avg_rel_humidity: float = 30.0,
    do_energy_valuation: bool = False,
    do_productivity_valuation: bool = False,
    building_vector_path: str = "",
    energy_consumption_table_path: str = "",
    cc_weight_shade: float = 0.6,
    cc_weight_albedo: float = 0.2,
    cc_weight_eti: float = 0.2,
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """Estimate the cooling effect of urban green spaces and quantify
    associated energy savings and work productivity benefits.

    Args:
        lulc_raster_path: Path to land use/land cover raster (linearly
            projected, units in meters).
        ref_eto_raster_path: Path to reference evapotranspiration raster.
        aoi_vector_path: Path to area of interest vector.
        biophysical_table_path: CSV mapping LULC codes to shade, Kc,
            albedo, and green_area values. Must include 'lucode', 'kc',
            'green_area'. Include 'shade' and 'albedo' for cc_method='factors';
            'building_intensity' for cc_method='intensity'.
        green_area_cooling_distance: Distance in meters over which large
            green areas (> 2 ha) exert a cooling effect.
        t_ref: Reference (rural) air temperature (°C).
        uhi_max: Maximum urban heat island effect magnitude (°C).
        cc_method: Cooling capacity method — 'factors' (weighted CC indices)
            or 'intensity' (NDVI/building-intensity based). Default: 'factors'.
        t_air_average_radius: Radius in meters for averaging air temperature. Default: 2000.
        avg_rel_humidity: Average relative humidity percentage 0–100. Default: 30.
        do_energy_valuation: If True, calculate energy savings for buildings. Default: False.
        do_productivity_valuation: If True, calculate work productivity gains. Default: False.
        building_vector_path: Path to building footprint vector with 'type'
            field (optional; required for energy valuation).
        energy_consumption_table_path: Path to CSV mapping building types to
            energy consumption (optional; required for energy valuation).
        cc_weight_shade: Shade weight for CC index (0–1, must sum to 1). Default: 0.6.
        cc_weight_albedo: Albedo weight for CC index (0–1). Default: 0.2.
        cc_weight_eti: ETI weight for CC index (0–1). Default: 0.2.
        workspace_dir: Output directory (auto-created if empty).
        results_suffix: Suffix appended to all output filenames.
    """
    import natcap.invest.urban_cooling_model

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "urban_cooling"))
    args = {
        "lulc_raster_path":            lulc_raster_path,
        "ref_eto_raster_path":         ref_eto_raster_path,
        "aoi_vector_path":             aoi_vector_path,
        "biophysical_table_path":      biophysical_table_path,
        "green_area_cooling_distance": green_area_cooling_distance,
        "t_ref":                       t_ref,
        "uhi_max":                     uhi_max,
        "cc_method":                   cc_method,
        "t_air_average_radius":        t_air_average_radius,
        "avg_rel_humidity":            avg_rel_humidity,
        "do_energy_valuation":         do_energy_valuation,
        "do_productivity_valuation":   do_productivity_valuation,
        "workspace_dir":               ws,
        "results_suffix":              results_suffix,
    }
    if cc_method == "factors":
        args["cc_weight_shade"]  = cc_weight_shade
        args["cc_weight_albedo"] = cc_weight_albedo
        args["cc_weight_eti"]    = cc_weight_eti
    if clean_optional(building_vector_path):
        args["building_vector_path"] = building_vector_path
    if clean_optional(energy_consumption_table_path):
        args["energy_consumption_table_path"] = energy_consumption_table_path

    return run_invest_model("Urban Cooling", natcap.invest.urban_cooling_model, args, ws)


# ========================================================================
# 20. Urban Flood Risk Mitigation
# ========================================================================
@mcp.tool()
def run_urban_flood(
    aoi_watersheds_path: str,
    rainfall_depth: float,
    lulc_path: str,
    soils_hydrological_group_raster_path: str,
    curve_number_table_path: str,
    built_infrastructure_vector_path: str = "",
    infrastructure_damage_loss_table_path: str = "",
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """Model urban flood risk mitigation by green infrastructure.

    Computes peak flow attenuation for each pixel using curve numbers, delineates
    benefiting areas, and optionally calculates avoided damage to built infrastructure.

    Args:
        aoi_watersheds_path: Path to (sub)watersheds or sewersheds shapefile.
        rainfall_depth: Depth of rainfall for the 24-hour design storm event (mm).
        lulc_path: Path to land use/land cover raster.
        soils_hydrological_group_raster_path: Path to soil hydrologic group
            raster (values 1=A, 2=B, 3=C, 4=D).
        curve_number_table_path: Path to CSV with columns lucode, CN_A, CN_B,
            CN_C, CN_D.
        built_infrastructure_vector_path: Path to built infrastructure
            footprints vector with a 'Type' integer field. (optional)
        infrastructure_damage_loss_table_path: Path to CSV with 'Type' and
            'Damage' (currency/m²) columns. (optional; required with
            built_infrastructure_vector_path)
        workspace_dir: Output directory (auto-created if empty).
        results_suffix: Suffix appended to all output filenames.
    """
    import natcap.invest.urban_flood_risk_mitigation

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "urban_flood"))
    args = {
        "aoi_watersheds_path":                aoi_watersheds_path,
        "rainfall_depth":                     rainfall_depth,
        "lulc_path":                          lulc_path,
        "soils_hydrological_group_raster_path": soils_hydrological_group_raster_path,
        "curve_number_table_path":            curve_number_table_path,
        "workspace_dir":                      ws,
        "results_suffix":                     results_suffix,
    }
    if clean_optional(built_infrastructure_vector_path):
        args["built_infrastructure_vector_path"] = built_infrastructure_vector_path
    if clean_optional(infrastructure_damage_loss_table_path):
        args["infrastructure_damage_loss_table_path"] = infrastructure_damage_loss_table_path

    return run_invest_model(
        "Urban Flood Risk Mitigation", natcap.invest.urban_flood_risk_mitigation, args, ws
    )


# ========================================================================
# 21. Urban Nature Access
# ========================================================================
@mcp.tool()
def run_urban_nature_access(
    lulc_raster_path: str,
    lulc_attribute_table: str,
    population_raster_path: str,
    admin_boundaries_vector_path: str,
    search_radius_mode: str,
    decay_function: str,
    urban_nature_demand: float = 100.0,
    search_radius: float = 0.0,
    population_group_radii_table: str = "",
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """Quantify resident access to urban nature (green/blue spaces).

    Measures proximity-weighted supply of urban nature relative to population,
    supporting equitable urban planning analysis.

    Args:
        lulc_raster_path: Path to LULC raster (linearly projected, meters).
        lulc_attribute_table: Path to CSV with columns lucode, urban_nature
            (proportion 0–1), and optionally search_radius_m.
        population_raster_path: Path to population raster (people per pixel,
            linearly projected, meters).
        admin_boundaries_vector_path: Path to administrative boundaries
            polygon vector for aggregating results.
        search_radius_mode: One of 'RADIUS_OPT_UNIFORM',
            'RADIUS_OPT_URBAN_NATURE', or 'RADIUS_OPT_POP_GROUP'.
        decay_function: Distance decay kernel — one of the keys in KERNEL_TYPES
            (e.g. 'gaussian', 'linear', 'dichotomy').
        urban_nature_demand: Required urban nature per capita in m². Default: 100.
        search_radius: Uniform search radius in meters (required when
            search_radius_mode='RADIUS_OPT_UNIFORM'). Default: 0.
        population_group_radii_table: Path to CSV mapping population group
            fieldnames to search radii. (optional; required for POP_GROUP mode)
        workspace_dir: Output directory (auto-created if empty).
        results_suffix: Suffix appended to all output filenames.
    """
    import natcap.invest.urban_nature_access

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "urban_nature_access"))
    args = {
        "lulc_raster_path":             lulc_raster_path,
        "lulc_attribute_table":         lulc_attribute_table,
        "population_raster_path":       population_raster_path,
        "admin_boundaries_vector_path": admin_boundaries_vector_path,
        "search_radius_mode":           search_radius_mode,
        "decay_function":               decay_function,
        "urban_nature_demand":          urban_nature_demand,
        "workspace_dir":                ws,
        "results_suffix":               results_suffix,
    }
    if search_radius > 0:
        args["search_radius"] = search_radius
    if clean_optional(population_group_radii_table):
        args["population_group_radii_table"] = population_group_radii_table

    return run_invest_model("Urban Nature Access", natcap.invest.urban_nature_access, args, ws)


# ========================================================================
# 22. Urban Stormwater Retention
# ========================================================================
@mcp.tool()
def run_urban_stormwater(
    lulc_path: str,
    soil_group_path: str,
    precipitation_path: str,
    biophysical_table: str,
    adjust_retention_ratios: bool = False,
    retention_radius: float = 0.0,
    road_centerlines_path: str = "",
    aggregate_areas_path: str = "",
    replacement_cost: float = 0.0,
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """Model urban stormwater retention, runoff, and water quality benefits.

    Computes retention ratios, runoff volumes, and pollutant loading per pixel
    and aggregated by watershed. Optionally values retained stormwater.

    Args:
        lulc_path: Path to LULC raster.
        soil_group_path: Path to soil group raster (values 1=A, 2=B, 3=C, 4=D).
        precipitation_path: Path to total annual precipitation raster (mm).
        biophysical_table: Path to biophysical CSV with lucode, EMC values,
            retention (RC) and percolation (PE) coefficients per soil group,
            and 'is_connected' if adjust_retention_ratios=True.
        adjust_retention_ratios: If True, reduce retention near roads. Default: False.
        retention_radius: Radius for road-adjustment algorithm (meters;
            required when adjust_retention_ratios=True).
        road_centerlines_path: Path to road centerlines vector (required
            when adjust_retention_ratios=True).
        aggregate_areas_path: Path to polygon vector for aggregating results. (optional)
        replacement_cost: Cost per m³ of retained stormwater (currency; optional).
        workspace_dir: Output directory (auto-created if empty).
        results_suffix: Suffix appended to all output filenames.
    """
    import natcap.invest.stormwater

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "urban_stormwater"))
    args = {
        "lulc_path":                  lulc_path,
        "soil_group_path":            soil_group_path,
        "precipitation_path":         precipitation_path,
        "biophysical_table":          biophysical_table,
        "adjust_retention_ratios":    adjust_retention_ratios,
        "workspace_dir":              ws,
        "results_suffix":             results_suffix,
    }
    if adjust_retention_ratios:
        args["retention_radius"] = retention_radius
        if clean_optional(road_centerlines_path):
            args["road_centerlines_path"] = road_centerlines_path
    if clean_optional(aggregate_areas_path):
        args["aggregate_areas_path"] = aggregate_areas_path
    if replacement_cost > 0:
        args["replacement_cost"] = replacement_cost

    return run_invest_model("Urban Stormwater Retention", natcap.invest.stormwater, args, ws)


# ========================================================================
# 23. Wave Energy Production
# ========================================================================
@mcp.tool()
def run_wave_energy(
    machine_perf_path: str,
    machine_param_path: str,
    wave_base_data_path: str,
    dem_path: str,
    aoi_path: str = "",
    valuation_container: bool = False,
    land_gridPts_path: str = "",
    machine_econ_path: str = "",
    number_of_machines: int = 28,
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """Estimate wave energy production and net present value.

    Executes both the biophysical and valuation components of the Wave Energy
    Model (WEM) to produce wave power, capacity, and NPV rasters.

    Args:
        machine_perf_path: Path to wave energy machine performance table CSV
            (capture width vs. wave period and height).
        machine_param_path: Path to machine parameters CSV (dimensions, rated
            capacity).
        wave_base_data_path: Path to the wave base data directory containing
            WAVEWATCH III global wave data.
        dem_path: Path to Global Digital Elevation Model (DEM) raster.
        aoi_path: Path to AOI polygon vector (required for valuation; clips
            analysis to a more detailed area within the wave data extent).
        valuation_container: If True, run economic valuation (requires
            land_gridPts_path and machine_econ_path). Default: False.
        land_gridPts_path: Path to CSV with landing and power grid connection
            points (required for valuation).
        machine_econ_path: Path to machine economic parameters CSV (required
            for valuation).
        number_of_machines: Number of wave energy machines per farm site
            (required for valuation). Default: 28.
        workspace_dir: Output directory (auto-created if empty).
        results_suffix: Suffix appended to all output filenames.
    """
    import natcap.invest.wave_energy

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "wave_energy"))
    args = {
        "machine_perf_path":  machine_perf_path,
        "machine_param_path": machine_param_path,
        "wave_base_data_path": wave_base_data_path,
        "dem_path":            dem_path,
        "workspace_dir":       ws,
        "results_suffix":      results_suffix,
    }
    if clean_optional(aoi_path):
        args["aoi_path"] = aoi_path
    if valuation_container:
        args["valuation_container"] = True
        args["number_of_machines"]  = number_of_machines
        if clean_optional(land_gridPts_path):
            args["land_gridPts_path"] = land_gridPts_path
        if clean_optional(machine_econ_path):
            args["machine_econ_path"] = machine_econ_path

    return run_invest_model("Wave Energy Production", natcap.invest.wave_energy, args, ws)


# ========================================================================
# 24. Offshore Wind Energy Production
# ========================================================================
@mcp.tool()
def run_offshore_wind_energy(
    wind_data_path: str,
    aoi_vector_path: str,
    bathymetry_path: str,
    land_polygon_vector_path: str,
    global_wind_parameters_path: str,
    turbine_parameters_path: str,
    number_of_turbines: int,
    min_depth: float = 3.0,
    max_depth: float = 60.0,
    min_distance: float = 0.0,
    max_distance: float = 200000.0,
    valuation_container: bool = False,
    avg_grid_distance: float = 4.0,
    grid_points_path: str = "",
    land_points_path: str = "",
    workspace_dir: str = "",
    results_suffix: str = "",
) -> str:
    """Map offshore wind energy potential and estimate energy production and NPV.

    Estimates wind power density, capacity factors, and net present value
    for offshore wind farms across a bathymetric domain.

    Args:
        wind_data_path: Path to wind data CSV with headers LONG, LATI, LAM
            (scale), K (shape), REF (reference height).
        aoi_vector_path: Path to AOI polygon vector projected in meters.
        bathymetry_path: Path to bathymetry raster (negative = depth in meters).
        land_polygon_vector_path: Path to land polygon vector for computing
            distance-to-shore.
        global_wind_parameters_path: Path to global wind parameters CSV
            (turbine and financial defaults).
        turbine_parameters_path: Path to turbine parameters CSV (hub height,
            rotor radius, rated capacity, and valuation parameters).
        number_of_turbines: Number of turbines in the wind farm (required for valuation).
        min_depth: Minimum water depth for installation (meters). Default: 3.
        max_depth: Maximum water depth for installation (meters). Default: 60.
        min_distance: Minimum distance from shore (meters). Default: 0.
        max_distance: Maximum distance from shore (meters). Default: 200 000.
        valuation_container: If True, run economic valuation. Default: False.
        avg_grid_distance: Average distance to grid connection (km; used
            when grid_points_path is not provided). Default: 4.
        grid_points_path: Path to CSV with grid/landing connection points. (optional)
        land_points_path: Path to CSV with land connection points. (optional)
        workspace_dir: Output directory (auto-created if empty).
        results_suffix: Suffix appended to all output filenames.
    """
    import natcap.invest.wind_energy

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "offshore_wind_energy"))
    args = {
        "wind_data_path":              wind_data_path,
        "aoi_vector_path":             aoi_vector_path,
        "bathymetry_path":             bathymetry_path,
        "land_polygon_vector_path":    land_polygon_vector_path,
        "global_wind_parameters_path": global_wind_parameters_path,
        "turbine_parameters_path":     turbine_parameters_path,
        "number_of_turbines":          number_of_turbines,
        "min_depth":                   min_depth,
        "max_depth":                   max_depth,
        "min_distance":                min_distance,
        "max_distance":                max_distance,
        "valuation_container":         valuation_container,
        "avg_grid_distance":           avg_grid_distance,
        "workspace_dir":               ws,
        "results_suffix":              results_suffix,
    }
    if clean_optional(grid_points_path):
        args["grid_points_path"] = grid_points_path
    if clean_optional(land_points_path):
        args["land_points_path"] = land_points_path

    return run_invest_model("Offshore Wind Energy", natcap.invest.wind_energy, args, ws)


# ========================================================================
# Entry point
# ========================================================================
_TOOL_COUNT = 25        # InVEST model tools (incl. CBC preprocessor)
_DISC_COUNT = 3         # discovery tools: list_models, list_sample_data, get_sample_args
_TOTAL      = _TOOL_COUNT + _DISC_COUNT


def main() -> None:
    """Start the InVEST MCP server.

    Transport is selected by --transport flag or the INVEST_MCP_TRANSPORT env var:

      stdio  — VS Code / Claude Code / Claude Desktop integration.
               The MCP client launches this process as a subprocess and
               communicates over stdin/stdout.  No port needed.

      sse    — Network server (default).  Useful for running the server
               once and connecting multiple clients, or for remote access.
               Listens on INVEST_MCP_PORT (default 54320).

    Usage:
        python server.py                    # SSE on port 54320
        python server.py --transport stdio  # stdio for VS Code
        invest-mcp --transport stdio        # same via entry point
    """
    import argparse as _ap
    parser = _ap.ArgumentParser(description="InVEST MCP Server")
    parser.add_argument(
        "--transport",
        choices=["sse", "stdio"],
        default=os.getenv("INVEST_MCP_TRANSPORT", "sse"),
        help="Transport: 'stdio' for VS Code/Claude Code, 'sse' for network (default: sse)",
    )
    a, _ = parser.parse_known_args()

    if a.transport == "stdio":
        logger.info("Starting InVEST MCP Server (stdio, %d tools)", _TOTAL)
        mcp.run(transport="stdio")
    else:
        port = int(os.getenv("INVEST_MCP_PORT", 54320))
        logger.info(
            "Starting InVEST MCP Server on port %d  (%d tools: %d InVEST models + %d discovery)",
            port, _TOTAL, _TOOL_COUNT, _DISC_COUNT,
        )
        mcp.settings.port = port
        mcp.run(transport="sse")


if __name__ == "__main__":
    main()
