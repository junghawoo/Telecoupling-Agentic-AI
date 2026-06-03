"""
shared/utils.py
~~~~~~~~~~~~~~~
Shared utilities for all Telecoupling tool modules.

Every tool file imports from here:
    from shared.utils import CSISError, validate_required, generate_output_dir,
                             scan_output_directory, run_r_script

Symbols
-------
CSISError               Custom exception with (message, error_code).
validate_required       Raise CSISError if required params are missing.
generate_output_dir     Create a per-session workspace directory.
scan_output_directory   Async — walk a workspace and return file metadata list.
run_r_script            Sync  — run an R script, passing a config dict as JSON.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CSISError
# ---------------------------------------------------------------------------

class CSISError(Exception):
    """
    Domain exception raised by tool modules.

    Attributes
    ----------
    code : str
        Machine-readable error code, e.g. ``"TOOL_FAILED"``,
        ``"VALIDATION_ERROR"``, ``"FILE_NOT_FOUND"``, ``"INVALID_PARAMS"``.

    Usage
    -----
    raise CSISError("dem_path is required", "VALIDATION_ERROR")
    """

    def __init__(self, message: str, code: str = "UNKNOWN_ERROR") -> None:
        super().__init__(message)
        self.code = code

    def __repr__(self) -> str:
        return f"CSISError({self.code!r}, {str(self)!r})"


# ---------------------------------------------------------------------------
# validate_required
# ---------------------------------------------------------------------------

def validate_required(params: dict, keys: list[str]) -> None:
    """Raise :class:`CSISError` if any key in *keys* is absent or empty.

    Parameters
    ----------
    params : dict
        The tool's raw parameter dictionary (from the agent request).
    keys : list[str]
        Names of required keys that must be present and non-empty.

    Raises
    ------
    CSISError
        With code ``"VALIDATION_ERROR"`` listing all missing keys.
    """
    missing = [k for k in keys if not params.get(k)]
    if missing:
        raise CSISError(
            f"Missing required parameter(s): {', '.join(missing)}",
            "VALIDATION_ERROR",
        )


# ---------------------------------------------------------------------------
# generate_output_dir
# ---------------------------------------------------------------------------

def generate_output_dir(model_name: str, session_id: str) -> tuple[str, str]:
    """Create and return a unique workspace directory for one model run.

    The directory is created at::

        {output_base_dir}/{model_name}_{session_id}/

    The base directory is resolved in this order:
        1. ``settings.output_base_dir``  (from ``app.core.config``)
        2. ``TELECOUPLING_OUTPUT_DIR`` environment variable
        3. ``./data/outputs`` (hard-coded fallback)

    Parameters
    ----------
    model_name : str
        Short model identifier, e.g. ``"coastal_blue_carbon"``.
    session_id : str
        Unique session identifier passed in by the calling agent.

    Returns
    -------
    workspace_dir : str
        Absolute path to the created directory.
    folder_name : str
        Just the leaf folder name (``"{model_name}_{session_id}"``).
    """
    try:
        from app.core.config import settings
        base = os.path.abspath(settings.output_base_dir)
    except Exception:
        base = os.path.abspath(
            os.environ.get("TELECOUPLING_OUTPUT_DIR", "./data/outputs")
        )

    folder_name = f"{model_name}_{session_id}"
    workspace_dir = os.path.join(base, folder_name)
    os.makedirs(workspace_dir, exist_ok=True)
    logger.debug("Workspace created: %s", workspace_dir)
    return workspace_dir, folder_name


# ---------------------------------------------------------------------------
# scan_output_directory
# ---------------------------------------------------------------------------

# Extension → render_type used by the frontend to choose a viewer
_EXT_RENDER_TYPE: dict[str, str] = {
    ".tif":     "raster",
    ".tiff":    "raster",
    ".png":     "image",
    ".jpg":     "image",
    ".jpeg":    "image",
    ".pdf":     "pdf",
    ".shp":     "vector",
    ".gpkg":    "vector",
    ".geojson": "vector",
    ".csv":     "table",
    ".txt":     "text",
    ".json":    "text",
    ".log":     "text",
}

# Shapefile sidecar extensions — group them under the .shp entry
_SHP_SIDECARS = {".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".shp.xml"}


async def scan_output_directory(
    workspace_dir: str,
    model_name: str,
) -> list[dict[str, Any]]:
    """Walk *workspace_dir* and return metadata for every output file.

    This function is ``async`` for consistency with the tool module interface
    (tools ``await`` it), but the underlying work is synchronous file I/O.

    Parameters
    ----------
    workspace_dir : str
        Directory to scan (typically the model's workspace or its
        ``output/`` sub-directory).
    model_name : str
        Used only for log messages.

    Returns
    -------
    list[dict]
        One entry per file, each containing:

        - ``filename``   — base filename
        - ``path``       — absolute path
        - ``size_bytes`` — file size in bytes
        - ``render_type``— frontend hint: ``"raster"``, ``"vector"``,
          ``"table"``, ``"image"``, ``"pdf"``, ``"text"``, or ``"file"``
    """
    files: list[dict[str, Any]] = []

    if not os.path.isdir(workspace_dir):
        logger.warning(
            "[%s] scan_output_directory: directory not found: %s",
            model_name, workspace_dir,
        )
        return files

    for root, _dirs, filenames in os.walk(workspace_dir):
        for fname in sorted(filenames):
            abs_path = os.path.join(root, fname)
            suffix = Path(fname).suffix.lower()

            # Skip shapefile sidecar files — the .shp entry covers them
            if suffix in _SHP_SIDECARS or Path(fname).name.endswith(".shp.xml"):
                continue
            # Skip hidden files and Python cache
            if fname.startswith(".") or "__pycache__" in root:
                continue

            try:
                size = os.path.getsize(abs_path)
            except OSError:
                size = 0

            render_type = _EXT_RENDER_TYPE.get(suffix, "file")
            files.append(
                {
                    "filename": fname,
                    "path": abs_path,
                    "size_bytes": size,
                    "render_type": render_type,
                }
            )

    logger.debug("[%s] scan found %d output file(s)", model_name, len(files))
    return files


# ---------------------------------------------------------------------------
# run_r_script
# ---------------------------------------------------------------------------

def run_r_script(
    script_path: str,
    config: dict[str, Any],
    session_id: str,
    task_id: str,
) -> None:
    """Run an R script synchronously, passing *config* as a JSON command-line argument.

    The R script receives the configuration via::

        args <- commandArgs(trailingOnly = TRUE)
        config <- jsonlite::fromJSON(args[1])

    The Rscript binary is resolved in this order:
        1. ``settings.r_executable``  (from ``app.core.config``)
        2. ``RSCRIPT_PATH`` environment variable
        3. ``"Rscript"`` (relies on PATH)

    Parameters
    ----------
    script_path : str
        Absolute path to the ``.R`` script.
    config : dict
        Parameters serialised to JSON and passed as ``args[1]`` in R.
    session_id : str
        Used in log messages for traceability.
    task_id : str
        Used in log messages for traceability.

    Raises
    ------
    CSISError
        With code ``"TOOL_FAILED"`` if the script exits with a non-zero
        status or raises an unexpected OS-level error.
    """
    # Resolve Rscript binary
    try:
        from app.core.config import settings
        rscript = settings.r_executable or "Rscript"
    except Exception:
        rscript = os.environ.get("RSCRIPT_PATH", "Rscript")

    config_json = json.dumps(config)
    cmd = [rscript, script_path, config_json]

    logger.info(
        "[session=%s task=%s] Running R script: %s", session_id, task_id, script_path
    )
    logger.debug("[session=%s] R config: %s", session_id, config_json[:500])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5-minute hard limit
        )
    except FileNotFoundError:
        raise CSISError(
            f"Rscript binary not found: '{rscript}'. "
            "Install R and set R_EXECUTABLE in .env, or ensure Rscript is on PATH.",
            "TOOL_FAILED",
        )
    except subprocess.TimeoutExpired:
        raise CSISError(
            f"R script timed out after 300 s: {script_path}",
            "TOOL_FAILED",
        )

    # Forward R messages (stderr) to the Python logger
    if result.stderr:
        for line in result.stderr.strip().splitlines():
            logger.info("[R] %s", line)

    if result.returncode != 0:
        stdout_tail = result.stdout.strip()[-500:] if result.stdout else ""
        stderr_tail = result.stderr.strip()[-500:] if result.stderr else ""
        raise CSISError(
            f"R script failed (exit {result.returncode}): {script_path}\n"
            f"stderr: {stderr_tail}\nstdout: {stdout_tail}",
            "TOOL_FAILED",
        )

    logger.info(
        "[session=%s task=%s] R script completed successfully", session_id, task_id
    )
