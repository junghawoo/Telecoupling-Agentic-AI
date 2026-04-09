"""
Telecoupling AI - QGIS MCP Server

Exposes QGIS geospatial processing operations as MCP tools.
Runs QGIS in headless mode (QT_QPA_PLATFORM=offscreen).

Must be launched with system Python (/usr/bin/python3) which has
PyQGIS bindings installed via apt.

Tools:
   1. list_operations        — Discover available tools
   2. list_algorithms        — Search QGIS Processing algorithms (679+)
   3. get_algorithm_details  — Get parameter info for an algorithm
   4. get_raster_info        — Inspect raster metadata & statistics
   5. get_vector_info        — Inspect vector metadata & fields
   6. reproject_raster       — Reproject a raster to a different CRS
   7. reproject_vector       — Reproject a vector to a different CRS
   8. clip_raster_by_mask    — Clip raster with a vector mask layer
   9. clip_vector_by_extent  — Clip vector features to a bounding extent
  10. buffer_vector          — Buffer vector features by distance
  11. vector_overlay         — Intersect / union / difference / symmetric_difference
  12. zonal_statistics       — Raster stats within polygon zones
  13. raster_calculator      — Band math on rasters (GDAL calc)
  14. render_map             — Render a styled map image from layers
  15. execute_processing     — Run ANY Processing algorithm by ID (generic)
"""

import json
import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: headless QGIS must be initialised before MCP starts
# ---------------------------------------------------------------------------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PROJ_LIB", "/usr/share/proj")
os.environ.setdefault("PROJ_DATA", "/usr/share/proj")

if "/usr/share/qgis/python/plugins" not in sys.path:
    sys.path.insert(0, "/usr/share/qgis/python/plugins")

from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Load .env from telecoupling-app root
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)

# Logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("qgis-mcp")

# Local helpers (must be imported after env setup)
from utils import (  # noqa: E402
    init_qgis,
    clean_optional,
    ensure_workspace,
    run_qgis_operation,
    format_result,
    get_raster_info as _get_raster_info,
    get_vector_info as _get_vector_info,
    list_all_algorithms as _list_all_algorithms,
    get_algorithm_help as _get_algorithm_help,
    run_processing_algorithm,
)

# Eagerly initialise QGIS so all tools can use it immediately
init_qgis()

OUTPUT_DIR = os.path.abspath(os.getenv("QGIS_OUTPUT_DIR", "./data/outputs"))

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "QGIS MCP Server",
    instructions=(
        "QGIS 3.34 geospatial processing exposed as MCP tools. "
        "679+ algorithms available via execute_processing. "
        "Use list_operations first to discover typed convenience tools, "
        "or list_algorithms / get_algorithm_details for any Processing algorithm."
    ),
)


# ========================================================================
# 1. list_operations  (discovery)
# ========================================================================
@mcp.tool()
def list_operations() -> str:
    """List all available QGIS geospatial operations (typed tools).

    Call this first to discover what convenience tools are available
    and what each one does.
    """
    operations = {
        "list_operations": "List all available typed QGIS tools (this tool)",
        "list_algorithms": "Search/list QGIS Processing algorithms (679+ from native, gdal, grass7)",
        "get_algorithm_details": "Get full parameter info for any Processing algorithm by ID",
        "get_raster_info": "Inspect raster metadata: CRS, dimensions, pixel size, band statistics",
        "get_vector_info": "Inspect vector metadata: CRS, geometry type, feature count, fields",
        "reproject_raster": "Reproject a raster to a different CRS (e.g. EPSG:4326)",
        "reproject_vector": "Reproject a vector layer to a different CRS",
        "clip_raster_by_mask": "Clip a raster using a vector polygon mask layer",
        "clip_vector_by_extent": "Clip vector features to a bounding box or another layer's extent",
        "buffer_vector": "Create buffer zones around vector features",
        "vector_overlay": "Perform overlay: intersect, union, difference, symmetric_difference",
        "zonal_statistics": "Calculate raster statistics within polygon zones",
        "raster_calculator": "Perform band math / raster algebra (GDAL raster calculator)",
        "render_map": "Render layers to a styled map image (PNG/JPG)",
        "execute_processing": "Run ANY QGIS Processing algorithm by its ID (generic escape-hatch)",
    }
    return json.dumps(operations, indent=2)


# ========================================================================
# 2. list_algorithms
# ========================================================================
@mcp.tool()
def list_algorithms(
    search: str = "",
    provider: str = "",
    limit: int = 50,
) -> str:
    """Search and list QGIS Processing algorithms.

    Returns algorithm IDs, names, and groups. Use get_algorithm_details
    to see full parameters for a specific algorithm.

    Args:
        search: Filter algorithms whose name or ID contains this text (case-insensitive). Empty = list all.
        provider: Filter by provider ID: 'native', 'gdal', 'grass7', 'qgis', '3d'. Empty = all providers.
        limit: Maximum number of results to return (default 50).
    """
    algos = _list_all_algorithms()

    # Apply filters
    if search:
        s = search.lower()
        algos = [a for a in algos if s in a["id"].lower() or s in a["name"].lower()]
    if provider:
        algos = [a for a in algos if a["provider"] == provider]

    total = len(algos)
    algos = algos[:limit]

    return json.dumps(
        {"total_matches": total, "returned": len(algos), "algorithms": algos},
        indent=2,
    )


# ========================================================================
# 3. get_algorithm_details
# ========================================================================
@mcp.tool()
def get_algorithm_details(algorithm_id: str) -> str:
    """Get full parameter information for a QGIS Processing algorithm.

    Use this before calling execute_processing to understand what
    parameters an algorithm expects.

    Args:
        algorithm_id: The algorithm ID, e.g. 'native:buffer', 'gdal:warpreproject'.
    """
    info = _get_algorithm_help(algorithm_id)
    if info is None:
        return json.dumps({"error": f"Algorithm '{algorithm_id}' not found"})
    return json.dumps(info, indent=2)


# ========================================================================
# 4. get_raster_info
# ========================================================================
@mcp.tool()
def get_raster_info(raster_path: str) -> str:
    """Get metadata and band statistics for a raster file.

    Returns CRS, dimensions, pixel size, extent, and per-band
    min/max/mean/stddev.

    Args:
        raster_path: Absolute path to the raster file (GeoTIFF, etc.)
    """
    info = _get_raster_info(raster_path)
    return json.dumps(info, indent=2)


# ========================================================================
# 5. get_vector_info
# ========================================================================
@mcp.tool()
def get_vector_info(vector_path: str) -> str:
    """Get metadata and field schema for a vector file.

    Returns CRS, geometry type, feature count, extent, and field
    names/types.

    Args:
        vector_path: Absolute path to the vector file (Shapefile, GeoPackage, GeoJSON)
    """
    info = _get_vector_info(vector_path)
    return json.dumps(info, indent=2)


# ========================================================================
# 6. reproject_raster
# ========================================================================
@mcp.tool()
def reproject_raster(
    input_raster: str,
    target_crs: str,
    output_path: str = "",
    resampling_method: str = "nearest",
    workspace_dir: str = "",
) -> str:
    """Reproject a raster to a different coordinate reference system.

    Args:
        input_raster: Path to input raster file
        target_crs: Target CRS as EPSG code, e.g. 'EPSG:4326', 'EPSG:32610'
        output_path: Path for output raster (auto-generated if empty)
        resampling_method: Resampling: 'nearest', 'bilinear', 'cubic', 'average', 'lanczos' (default: nearest)
        workspace_dir: Output directory (auto-created if empty)
    """
    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "reproject_raster"))
    if not output_path:
        base = Path(input_raster).stem
        output_path = os.path.join(ws, f"{base}_reprojected.tif")

    RESAMPLE_MAP = {
        "nearest": 0,
        "bilinear": 1,
        "cubic": 2,
        "cubicspline": 3,
        "lanczos": 4,
        "average": 5,
    }

    params = {
        "INPUT": input_raster,
        "TARGET_CRS": target_crs,
        "RESAMPLING": RESAMPLE_MAP.get(resampling_method.lower(), 0),
        "OUTPUT": output_path,
    }
    return run_qgis_operation("Reproject Raster", "gdal:warpreproject", params, ws)


# ========================================================================
# 7. reproject_vector
# ========================================================================
@mcp.tool()
def reproject_vector(
    input_vector: str,
    target_crs: str,
    output_path: str = "",
    workspace_dir: str = "",
) -> str:
    """Reproject a vector layer to a different coordinate reference system.

    Args:
        input_vector: Path to input vector file (Shapefile, GeoPackage, GeoJSON)
        target_crs: Target CRS as EPSG code, e.g. 'EPSG:4326'
        output_path: Path for output vector (auto-generated if empty)
        workspace_dir: Output directory (auto-created if empty)
    """
    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "reproject_vector"))
    if not output_path:
        base = Path(input_vector).stem
        output_path = os.path.join(ws, f"{base}_reprojected.gpkg")

    params = {
        "INPUT": input_vector,
        "TARGET_CRS": target_crs,
        "OUTPUT": output_path,
    }
    return run_qgis_operation("Reproject Vector", "native:reprojectlayer", params, ws)


# ========================================================================
# 8. clip_raster_by_mask
# ========================================================================
@mcp.tool()
def clip_raster_by_mask(
    input_raster: str,
    mask_layer: str,
    output_path: str = "",
    crop_to_cutline: bool = True,
    keep_resolution: bool = True,
    nodata_value: float = -9999.0,
    workspace_dir: str = "",
) -> str:
    """Clip a raster using a vector polygon mask layer.

    Args:
        input_raster: Path to input raster file
        mask_layer: Path to vector polygon used as clip mask
        output_path: Path for clipped output raster (auto-generated if empty)
        crop_to_cutline: Crop raster extent to mask extent (default True)
        keep_resolution: Keep original raster resolution (default True)
        nodata_value: NoData value for clipped areas (default -9999)
        workspace_dir: Output directory
    """
    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "clip_raster"))
    if not output_path:
        base = Path(input_raster).stem
        output_path = os.path.join(ws, f"{base}_clipped.tif")

    params = {
        "INPUT": input_raster,
        "MASK": mask_layer,
        "CROP_TO_CUTLINE": crop_to_cutline,
        "KEEP_RESOLUTION": keep_resolution,
        "NODATA": nodata_value,
        "OUTPUT": output_path,
    }
    return run_qgis_operation("Clip Raster by Mask", "gdal:cliprasterbymasklayer", params, ws)


# ========================================================================
# 9. clip_vector_by_extent
# ========================================================================
@mcp.tool()
def clip_vector_by_extent(
    input_vector: str,
    extent: str,
    output_path: str = "",
    workspace_dir: str = "",
) -> str:
    """Clip vector features to a bounding extent.

    Args:
        input_vector: Path to input vector file
        extent: Clipping extent as 'xmin,xmax,ymin,ymax' or path to a layer whose extent will be used
        output_path: Path for output vector (auto-generated if empty)
        workspace_dir: Output directory
    """
    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "clip_vector"))
    if not output_path:
        base = Path(input_vector).stem
        output_path = os.path.join(ws, f"{base}_clipped.gpkg")

    params = {
        "INPUT": input_vector,
        "EXTENT": extent,
        "OUTPUT": output_path,
    }
    return run_qgis_operation("Clip Vector by Extent", "gdal:clipvectorbyextent", params, ws)


# ========================================================================
# 10. buffer_vector
# ========================================================================
@mcp.tool()
def buffer_vector(
    input_vector: str,
    distance: float,
    output_path: str = "",
    segments: int = 5,
    dissolve: bool = False,
    end_cap_style: str = "round",
    workspace_dir: str = "",
) -> str:
    """Create buffer zones around vector features.

    Args:
        input_vector: Path to input vector file
        distance: Buffer distance in layer CRS units (meters for projected, degrees for geographic)
        output_path: Path for output buffered vector (auto-generated if empty)
        segments: Number of segments per quarter circle (default 5)
        dissolve: Dissolve all buffers into one geometry (default False)
        end_cap_style: End cap: 'round', 'flat', 'square' (default round)
        workspace_dir: Output directory
    """
    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "buffer_vector"))
    if not output_path:
        base = Path(input_vector).stem
        output_path = os.path.join(ws, f"{base}_buffered.gpkg")

    CAP_MAP = {"round": 0, "flat": 1, "square": 2}

    params = {
        "INPUT": input_vector,
        "DISTANCE": distance,
        "SEGMENTS": segments,
        "DISSOLVE": dissolve,
        "END_CAP_STYLE": CAP_MAP.get(end_cap_style.lower(), 0),
        "OUTPUT": output_path,
    }
    return run_qgis_operation("Buffer Vector", "native:buffer", params, ws)


# ========================================================================
# 11. vector_overlay
# ========================================================================
@mcp.tool()
def vector_overlay(
    input_vector: str,
    overlay_vector: str,
    operation: str = "intersection",
    output_path: str = "",
    workspace_dir: str = "",
) -> str:
    """Perform a vector overlay operation between two layers.

    Args:
        input_vector: Path to first input vector
        overlay_vector: Path to second (overlay) vector
        operation: One of: 'intersection', 'union', 'difference', 'symmetric_difference'
        output_path: Path for output vector (auto-generated if empty)
        workspace_dir: Output directory
    """
    OPERATION_MAP = {
        "intersection": "native:intersection",
        "union": "native:union",
        "difference": "native:difference",
        "symmetric_difference": "native:symmetricaldifference",
    }

    op = operation.lower()
    algorithm_id = OPERATION_MAP.get(op)
    if algorithm_id is None:
        return json.dumps(
            {
                "error": f"Unknown overlay operation '{operation}'. "
                f"Use one of: {list(OPERATION_MAP.keys())}"
            }
        )

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "vector_overlay"))
    if not output_path:
        base = Path(input_vector).stem
        output_path = os.path.join(ws, f"{base}_{op}.gpkg")

    params = {
        "INPUT": input_vector,
        "OVERLAY": overlay_vector,
        "OUTPUT": output_path,
    }
    return run_qgis_operation(f"Vector Overlay ({op})", algorithm_id, params, ws)


# ========================================================================
# 12. zonal_statistics
# ========================================================================
@mcp.tool()
def zonal_statistics(
    input_raster: str,
    input_zones: str,
    band: int = 1,
    statistics: str = "mean,min,max,sum,count",
    output_path: str = "",
    prefix: str = "zs_",
    workspace_dir: str = "",
) -> str:
    """Calculate raster statistics within polygon zones.

    Computes selected statistics of raster values for each polygon.

    Args:
        input_raster: Path to input raster file
        input_zones: Path to polygon vector defining zones
        band: Raster band number to analyze (default 1)
        statistics: Comma-separated stats: 'count,sum,mean,median,min,max,stdev,variance,minority,majority,range' (default: mean,min,max,sum,count)
        output_path: Path for output vector with stats columns (auto-generated if empty)
        prefix: Column name prefix for statistics (default 'zs_')
        workspace_dir: Output directory
    """
    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "zonal_statistics"))
    if not output_path:
        base = Path(input_zones).stem
        output_path = os.path.join(ws, f"{base}_zonal.gpkg")

    # Map stat names to QGIS native:zonalstatisticsfb flag values
    STAT_FLAGS = {
        "count": 0,
        "sum": 1,
        "mean": 2,
        "median": 3,
        "stdev": 4,
        "min": 5,
        "max": 6,
        "range": 7,
        "minority": 8,
        "majority": 9,
        "variance": 10,
    }

    stat_list = [s.strip().lower() for s in statistics.split(",")]
    stat_values = [STAT_FLAGS[s] for s in stat_list if s in STAT_FLAGS]

    params = {
        "INPUT": input_zones,
        "INPUT_RASTER": input_raster,
        "RASTER_BAND": band,
        "COLUMN_PREFIX": prefix,
        "STATISTICS": stat_values,
        "OUTPUT": output_path,
    }
    return run_qgis_operation("Zonal Statistics", "native:zonalstatisticsfb", params, ws)


# ========================================================================
# 13. raster_calculator
# ========================================================================
@mcp.tool()
def raster_calculator(
    input_a: str,
    expression: str,
    output_path: str = "",
    band_a: int = 1,
    input_b: str = "",
    band_b: int = 1,
    input_c: str = "",
    band_c: int = 1,
    no_data: float = -9999.0,
    output_type: int = 5,
    workspace_dir: str = "",
) -> str:
    """Perform raster algebra using GDAL Raster Calculator.

    Use A, B, C to reference input rasters in the expression.

    Example expressions:
      - 'A * 2.5'            (scale raster A)
      - 'A + B'              (add two rasters)
      - '(A - B) / (A + B)'  (NDVI-style normalized difference)
      - 'A * (A > 0)'        (mask: keep only positive values)

    Args:
        input_a: Path to input raster A (required)
        expression: Raster algebra expression using A, B, C references
        output_path: Path for output raster (auto-generated if empty)
        band_a: Band number for raster A (default 1)
        input_b: Path to input raster B (optional)
        band_b: Band number for raster B (default 1)
        input_c: Path to input raster C (optional)
        band_c: Band number for raster C (default 1)
        no_data: Output NoData value (default -9999)
        output_type: Output type: 0=Byte, 1=Int16, 2=UInt16, 3=UInt32, 4=Int32, 5=Float32, 6=Float64 (default 5=Float32)
        workspace_dir: Output directory
    """
    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "raster_calc"))
    if not output_path:
        output_path = os.path.join(ws, "calc_result.tif")

    params = {
        "INPUT_A": input_a,
        "BAND_A": band_a,
        "FORMULA": expression,
        "NO_DATA": no_data,
        "RTYPE": output_type,
        "OUTPUT": output_path,
    }

    if clean_optional(input_b):
        params["INPUT_B"] = input_b
        params["BAND_B"] = band_b
    if clean_optional(input_c):
        params["INPUT_C"] = input_c
        params["BAND_C"] = band_c

    return run_qgis_operation("Raster Calculator", "gdal:rastercalculator", params, ws)


# ========================================================================
# 14. render_map
# ========================================================================
@mcp.tool()
def render_map(
    layers: str,
    output_path: str = "",
    width: int = 1024,
    height: int = 768,
    extent: str = "",
    dpi: int = 96,
    workspace_dir: str = "",
) -> str:
    """Render one or more layers to a styled map image.

    Args:
        layers: Comma-separated layer paths. First layer drawn on bottom.
                Supports raster (.tif) and vector (.shp, .gpkg, .geojson).
        output_path: Path for the output PNG image (auto-generated if empty)
        width: Image width in pixels (default 1024)
        height: Image height in pixels (default 768)
        extent: Render extent as 'xmin,ymin,xmax,ymax'. Empty = auto-fit all layers.
        dpi: Image DPI (default 96)
        workspace_dir: Output directory
    """
    import time

    from qgis.core import (
        QgsMapSettings,
        QgsMapRendererSequentialJob,
        QgsRasterLayer,
        QgsVectorLayer,
        QgsRectangle,
        QgsCoordinateReferenceSystem,
    )
    from qgis.PyQt.QtCore import QSize

    start = time.time()

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "render_map"))
    if not output_path:
        output_path = os.path.join(ws, "map_render.png")

    # Load layers
    layer_paths = [p.strip() for p in layers.split(",")]
    qgs_layers = []
    for lp in layer_paths:
        if lp.lower().endswith((".tif", ".tiff", ".img", ".vrt")):
            layer = QgsRasterLayer(lp, Path(lp).stem)
        else:
            layer = QgsVectorLayer(lp, Path(lp).stem, "ogr")

        if not layer.isValid():
            return json.dumps({"error": f"Cannot load layer: {lp}"})
        qgs_layers.append(layer)

    # Map settings
    settings = QgsMapSettings()
    settings.setOutputSize(QSize(width, height))
    settings.setOutputDpi(dpi)
    settings.setLayers(qgs_layers)

    # Extent
    if extent:
        parts = [float(x) for x in extent.split(",")]
        settings.setExtent(QgsRectangle(parts[0], parts[1], parts[2], parts[3]))
    else:
        # Union of all layer extents
        full_extent = qgs_layers[0].extent()
        for layer in qgs_layers[1:]:
            full_extent.combineExtentWith(layer.extent())
        # Add 5% padding
        full_extent.grow(full_extent.width() * 0.05)
        settings.setExtent(full_extent)

    # Use CRS of first layer
    settings.setDestinationCrs(qgs_layers[0].crs())

    # Render
    job = QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()

    image = job.renderedImage()
    image.save(output_path)

    elapsed = time.time() - start

    return format_result(
        status="success",
        operation="Render Map",
        elapsed=elapsed,
        workspace_dir=ws,
        output_files=[os.path.basename(output_path)],
        details={
            "output_image": output_path,
            "size": f"{width}x{height}",
            "dpi": dpi,
            "layers": layer_paths,
        },
    )


# ========================================================================
# 15. execute_processing — generic escape-hatch
# ========================================================================
@mcp.tool()
def execute_processing(
    algorithm_id: str,
    parameters: str,
    workspace_dir: str = "",
) -> str:
    """Run ANY QGIS Processing algorithm by its ID.

    This is the generic escape-hatch that can run any of the 679+
    algorithms. Use list_algorithms and get_algorithm_details to discover
    algorithm IDs and their parameters first.

    Args:
        algorithm_id: Full algorithm ID, e.g. 'native:centroids', 'gdal:hillshade', 'grass7:r.slope.aspect'
        parameters: JSON string of algorithm parameters.
                    Example: '{"INPUT": "/path/to/layer.shp", "OUTPUT": "/path/to/result.gpkg"}'
        workspace_dir: Output directory (auto-created if empty)
    """
    try:
        params = json.loads(parameters)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON in parameters: {e}"})

    ws = ensure_workspace(workspace_dir, os.path.join(OUTPUT_DIR, "processing"))

    return run_qgis_operation(
        f"Processing: {algorithm_id}",
        algorithm_id,
        params,
        ws,
    )


# ========================================================================
# Entry point
# ========================================================================
if __name__ == "__main__":
    port = int(os.getenv("QGIS_MCP_PORT", 54321))
    logger.info(f"Starting QGIS MCP Server on port {port} (15 tools)")
    mcp.settings.port = port
    mcp.run(transport="sse")
