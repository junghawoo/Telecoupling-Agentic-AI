"""
Telecoupling AI - QGIS MCP Server: Shared Utilities

Headless QGIS initialization, processing helpers, and output formatting.
Must run under /usr/bin/python3 (system Python with PyQGIS bindings).
"""

import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

logger = logging.getLogger("qgis-mcp")

# ---------------------------------------------------------------------------
# QGIS headless bootstrap
# ---------------------------------------------------------------------------

_qgs_app = None  # singleton


def init_qgis():
    """Initialize QGIS Application in headless mode (once).

    Sets up:
      - QT_QPA_PLATFORM=offscreen  (no display)
      - PROJ_LIB pointing to system PROJ database
      - QGIS Processing framework with all providers
    """
    global _qgs_app
    if _qgs_app is not None:
        return _qgs_app

    # Headless Qt
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    # Use system PROJ database (avoid conda PROJ version mismatch)
    os.environ["PROJ_LIB"] = "/usr/share/proj"
    os.environ["PROJ_DATA"] = "/usr/share/proj"

    # Ensure QGIS Processing plugins are importable
    plugins_path = "/usr/share/qgis/python/plugins"
    if plugins_path not in sys.path:
        sys.path.insert(0, plugins_path)

    from qgis.core import QgsApplication, Qgis

    _qgs_app = QgsApplication([], False)
    _qgs_app.setPrefixPath("/usr", True)
    _qgs_app.initQgis()

    # Initialize Processing framework (loads native, gdal, grass, etc.)
    from processing.core.Processing import Processing

    Processing.initialize()

    reg = _qgs_app.processingRegistry()
    providers = [p.id() for p in reg.providers()]
    n_algos = len(list(reg.algorithms()))
    logger.info(f"QGIS {Qgis.version()} initialized — {len(providers)} providers, {n_algos} algorithms")
    logger.info(f"Providers: {providers}")

    return _qgs_app


def get_qgis_app():
    """Return the singleton QgsApplication (initializes if needed)."""
    if _qgs_app is None:
        init_qgis()
    return _qgs_app


# ---------------------------------------------------------------------------
# Processing helpers
# ---------------------------------------------------------------------------


def run_processing_algorithm(
    algorithm_id: str,
    parameters: dict,
    context=None,
    feedback=None,
) -> dict:
    """Execute a QGIS Processing algorithm and return its outputs.

    Args:
        algorithm_id: Full algorithm ID, e.g. 'native:buffer', 'gdal:warpreproject'.
        parameters: Algorithm parameter dict.
        context: Optional QgsProcessingContext.
        feedback: Optional QgsProcessingFeedback.

    Returns:
        Dict with 'OUTPUT' and other algorithm-specific output keys.
    """
    import processing

    app = get_qgis_app()

    if context is None:
        from qgis.core import QgsProcessingContext

        context = QgsProcessingContext()

    if feedback is None:
        from qgis.core import QgsProcessingFeedback

        feedback = QgsProcessingFeedback()

    result = processing.run(algorithm_id, parameters, context=context, feedback=feedback)
    return result


def list_all_algorithms() -> list[dict]:
    """Return a list of all registered Processing algorithms with metadata.

    Each entry has: id, name, group, provider, short_description.
    """
    app = get_qgis_app()
    reg = app.processingRegistry()
    algos = []
    for alg in reg.algorithms():
        algos.append(
            {
                "id": alg.id(),
                "name": alg.displayName(),
                "group": alg.group(),
                "provider": alg.provider().id() if alg.provider() else "unknown",
                "short_description": alg.shortDescription() or "",
            }
        )
    return algos


def get_algorithm_help(algorithm_id: str) -> dict | None:
    """Return parameter details for a specific algorithm.

    Returns dict with: id, name, description, parameters (list of param metadata).
    """
    app = get_qgis_app()
    reg = app.processingRegistry()
    alg = reg.algorithmById(algorithm_id)
    if alg is None:
        return None

    params = []
    for p in alg.parameterDefinitions():
        params.append(
            {
                "name": p.name(),
                "description": p.description(),
                "type": p.type(),
                "default": str(p.defaultValue()) if p.defaultValue() is not None else None,
                "optional": bool(
                    p.flags() & p.FlagOptional
                ),
            }
        )

    return {
        "id": alg.id(),
        "name": alg.displayName(),
        "group": alg.group(),
        "provider": alg.provider().id() if alg.provider() else "unknown",
        "description": alg.shortDescription() or alg.displayName(),
        "parameters": params,
    }


# ---------------------------------------------------------------------------
# Layer / file inspection utilities
# ---------------------------------------------------------------------------


def get_raster_info(raster_path: str) -> dict:
    """Get detailed metadata for a raster file using QGIS."""
    from qgis.core import QgsRasterLayer

    app = get_qgis_app()

    layer = QgsRasterLayer(raster_path, "temp_raster")
    if not layer.isValid():
        return {"error": f"Cannot open raster: {raster_path}"}

    provider = layer.dataProvider()
    extent = layer.extent()

    info = {
        "file": os.path.basename(raster_path),
        "path": raster_path,
        "crs": layer.crs().authid(),
        "crs_description": layer.crs().description(),
        "width": layer.width(),
        "height": layer.height(),
        "band_count": layer.bandCount(),
        "pixel_size_x": layer.rasterUnitsPerPixelX(),
        "pixel_size_y": layer.rasterUnitsPerPixelY(),
        "extent": {
            "xmin": extent.xMinimum(),
            "ymin": extent.yMinimum(),
            "xmax": extent.xMaximum(),
            "ymax": extent.yMaximum(),
        },
    }

    # Band statistics
    bands = []
    for i in range(1, layer.bandCount() + 1):
        stats = provider.bandStatistics(i)
        bands.append(
            {
                "band": i,
                "min": round(stats.minimumValue, 6),
                "max": round(stats.maximumValue, 6),
                "mean": round(stats.mean, 6),
                "stddev": round(stats.stdDev, 6),
            }
        )
    info["bands"] = bands

    return info


def get_vector_info(vector_path: str) -> dict:
    """Get detailed metadata for a vector file using QGIS."""
    from qgis.core import QgsVectorLayer

    app = get_qgis_app()

    layer = QgsVectorLayer(vector_path, "temp_vector", "ogr")
    if not layer.isValid():
        return {"error": f"Cannot open vector: {vector_path}"}

    extent = layer.extent()
    geom_type_map = {0: "Point", 1: "Line", 2: "Polygon", 3: "Unknown", 4: "Null"}

    fields = []
    for field in layer.fields():
        fields.append(
            {
                "name": field.name(),
                "type": field.typeName(),
                "length": field.length(),
            }
        )

    info = {
        "file": os.path.basename(vector_path),
        "path": vector_path,
        "crs": layer.crs().authid(),
        "crs_description": layer.crs().description(),
        "geometry_type": geom_type_map.get(layer.geometryType(), "Unknown"),
        "feature_count": layer.featureCount(),
        "extent": {
            "xmin": extent.xMinimum(),
            "ymin": extent.yMinimum(),
            "xmax": extent.xMaximum(),
            "ymax": extent.yMaximum(),
        },
        "fields": fields,
    }
    return info


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def ensure_workspace(workspace_dir: str, default_base: str) -> str:
    """Create a workspace directory, using a default if none specified."""
    if not workspace_dir:
        workspace_dir = default_base
    workspace = os.path.abspath(workspace_dir)
    os.makedirs(workspace, exist_ok=True)
    return workspace


def collect_output_files(
    workspace_dir: str,
    extensions: tuple = (".tif", ".shp", ".csv", ".gpkg", ".geojson", ".png", ".jpg"),
) -> dict:
    """Walk workspace and collect output files by extension."""
    outputs = {}
    for root, _dirs, files in os.walk(workspace_dir):
        for f in sorted(files):
            if f.lower().endswith(extensions):
                abs_path = os.path.join(root, f)
                rel_path = os.path.relpath(abs_path, workspace_dir)
                outputs[rel_path] = abs_path
    return outputs


def format_result(
    status: str,
    operation: str,
    elapsed: float,
    workspace_dir: str = "",
    output_files: list | None = None,
    details: dict | None = None,
    error: str = "",
    error_type: str = "",
) -> str:
    """Build a standardized JSON result string."""
    result = {
        "status": status,
        "operation": operation,
        "elapsed_seconds": round(elapsed, 2),
    }
    if workspace_dir:
        result["workspace_dir"] = workspace_dir
    if output_files:
        result["output_files"] = output_files
    if details:
        result["details"] = details
    if error:
        result["error"] = error
        result["error_type"] = error_type
    return json.dumps(result, indent=2)


def run_qgis_operation(
    operation_name: str,
    algorithm_id: str,
    parameters: dict,
    workspace_dir: str,
) -> str:
    """Execute a QGIS processing algorithm and return standardized results.

    This is the QGIS analog of InVEST's run_invest_model().

    Args:
        operation_name: Human-readable operation name.
        algorithm_id: QGIS Processing algorithm ID.
        parameters: Algorithm parameters dict.
        workspace_dir: Output directory.

    Returns:
        JSON string with status, outputs, and details.
    """
    start = time.time()
    logger.info(f"Starting {operation_name} ({algorithm_id})")
    logger.info(f"Params: {json.dumps({k: str(v)[:120] for k, v in parameters.items()}, indent=2)}")

    try:
        result = run_processing_algorithm(algorithm_id, parameters)
        elapsed = time.time() - start
        logger.info(f"{operation_name} completed in {elapsed:.2f}s")

        # Collect outputs from workspace
        output_files = collect_output_files(workspace_dir)

        # Also include direct algorithm outputs (paths)
        algo_outputs = {}
        for k, v in result.items():
            if isinstance(v, str) and os.path.isfile(v):
                algo_outputs[k] = v
            elif isinstance(v, str):
                algo_outputs[k] = v

        return format_result(
            status="success",
            operation=operation_name,
            elapsed=elapsed,
            workspace_dir=workspace_dir,
            output_files=list(output_files.keys()),
            details={"algorithm_id": algorithm_id, "algorithm_outputs": algo_outputs},
        )

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"{operation_name} failed after {elapsed:.2f}s: {e}")
        logger.error(traceback.format_exc())
        return format_result(
            status="error",
            operation=operation_name,
            elapsed=elapsed,
            workspace_dir=workspace_dir,
            error=str(e),
            error_type=type(e).__name__,
        )


def clean_optional(value: str) -> str | None:
    """Convert empty strings to None for optional parameters."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    return value
