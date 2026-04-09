"""
Telecoupling AI - InVEST MCP Server: Shared Utilities

Common helpers for running InVEST models, collecting outputs, and formatting results.
"""

import json
import logging
import os
import time
import traceback
from pathlib import Path
from typing import Any

from osgeo import gdal

gdal.UseExceptions()

logger = logging.getLogger("invest-mcp")


def ensure_workspace(workspace_dir: str, default_base: str) -> str:
    """Create a unique workspace directory for a model run.

    Args:
        workspace_dir: User-provided workspace path (empty = use default).
        default_base: Fallback base directory.

    Returns:
        Absolute path to the workspace directory (created if needed).
    """
    if not workspace_dir:
        workspace_dir = default_base
    workspace = os.path.abspath(workspace_dir)
    os.makedirs(workspace, exist_ok=True)
    return workspace


def collect_output_files(workspace_dir: str, extensions: tuple = (".tif", ".shp", ".csv", ".gpkg")) -> dict:
    """Walk a workspace directory and collect output files by extension.

    Returns:
        Dict mapping relative path to absolute path for each output file.
    """
    outputs = {}
    for root, _dirs, files in os.walk(workspace_dir):
        for f in sorted(files):
            if f.lower().endswith(extensions):
                abs_path = os.path.join(root, f)
                rel_path = os.path.relpath(abs_path, workspace_dir)
                outputs[rel_path] = abs_path
    return outputs


def get_raster_summary(raster_path: str) -> dict:
    """Get basic statistics for a raster file.

    Returns:
        Dict with min, max, mean, nodata, shape, crs info.
    """
    try:
        ds = gdal.Open(raster_path, gdal.GA_ReadOnly)
        if ds is None:
            return {"error": f"Cannot open {raster_path}"}

        band = ds.GetRasterBand(1)
        stats = band.GetStatistics(True, True)  # approx=True, force=True
        nodata = band.GetNoDataValue()
        result = {
            "file": os.path.basename(raster_path),
            "rows": ds.RasterYSize,
            "cols": ds.RasterXSize,
            "bands": ds.RasterCount,
            "min": round(stats[0], 6) if stats[0] is not None else None,
            "max": round(stats[1], 6) if stats[1] is not None else None,
            "mean": round(stats[2], 6) if stats[2] is not None else None,
            "stddev": round(stats[3], 6) if stats[3] is not None else None,
            "nodata": nodata,
            "projection": ds.GetProjection()[:80] if ds.GetProjection() else "unknown",
        }
        ds = None
        return result
    except Exception as e:
        return {"error": str(e)}


def run_invest_model(
    model_name: str,
    module: Any,
    args: dict,
    workspace_dir: str,
) -> str:
    """Execute an InVEST model and return structured JSON results.

    Args:
        model_name: Human-readable model name.
        module: The InVEST module with an execute() function.
        args: The args dict for the model.
        workspace_dir: The workspace directory for outputs.

    Returns:
        JSON string with status, outputs, and optional raster summaries.
    """
    start_time = time.time()
    logger.info(f"Starting {model_name} in {workspace_dir}")
    logger.info(f"Args: {json.dumps({k: str(v)[:100] for k, v in args.items()}, indent=2)}")

    try:
        module.execute(args)
        elapsed = round(time.time() - start_time, 2)
        logger.info(f"{model_name} completed in {elapsed}s")

        # Collect output files
        output_files = collect_output_files(workspace_dir)

        # Get raster summaries for .tif files
        raster_summaries = {}
        for rel_path, abs_path in output_files.items():
            if abs_path.lower().endswith(".tif"):
                raster_summaries[rel_path] = get_raster_summary(abs_path)

        result = {
            "status": "success",
            "model": model_name,
            "workspace_dir": workspace_dir,
            "elapsed_seconds": elapsed,
            "output_files": list(output_files.keys()),
            "raster_summaries": raster_summaries,
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        elapsed = round(time.time() - start_time, 2)
        logger.error(f"{model_name} failed after {elapsed}s: {e}")
        logger.error(traceback.format_exc())
        result = {
            "status": "error",
            "model": model_name,
            "error": str(e),
            "error_type": type(e).__name__,
            "elapsed_seconds": elapsed,
            "workspace_dir": workspace_dir,
        }
        return json.dumps(result, indent=2)


def clean_optional(value: str) -> str | None:
    """Convert empty strings to None for optional parameters."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    return value
