"""
Telecoupling AI - File Upload Router

Endpoints:
  POST   /files/upload       Upload a geospatial file (.tif, .csv, .shp, .gpkg, .geojson)
  GET    /files              List previously uploaded files
  DELETE /files/{filename}   Delete an uploaded file
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import settings

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_EXTENSIONS = {".tif", ".tiff", ".csv", ".shp", ".gpkg", ".geojson", ".json", ".zip"}
MAX_FILENAME_LENGTH = 255


def _upload_dir() -> Path:
    d = Path(settings.upload_dir).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_filename(name: str) -> str:
    """Strip path separators and dots that could escape the upload directory."""
    return Path(name).name  # keeps only the final component


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post("/upload", summary="Upload a geospatial file")
async def upload_file(file: UploadFile = File(...)):
    original = _safe_filename(file.filename or "upload")
    ext = Path(original).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Extension '{ext}' not accepted. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    upload_dir = _upload_dir()
    dest = upload_dir / original

    # Avoid overwriting: append _1, _2, … until the name is free
    stem = Path(original).stem
    counter = 1
    while dest.exists():
        dest = upload_dir / f"{stem}_{counter}{ext}"
        counter += 1

    try:
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
    finally:
        await file.close()

    return {
        "filename": dest.name,
        "path": str(dest),
        "size_bytes": dest.stat().st_size,
        "extension": ext,
    }


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get("", summary="List uploaded files")
async def list_files():
    upload_dir = _upload_dir()
    files = [
        {
            "filename": p.name,
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "extension": p.suffix.lower(),
        }
        for p in sorted(upload_dir.iterdir())
        if p.is_file() and p.suffix.lower() in ALLOWED_EXTENSIONS
    ]
    return {"count": len(files), "files": files}


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete("/{filename}", summary="Delete an uploaded file")
async def delete_file(filename: str):
    safe = _safe_filename(filename)
    if safe != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    dest = _upload_dir() / safe
    if not dest.exists():
        raise HTTPException(status_code=404, detail=f"'{filename}' not found")

    dest.unlink()
    return {"deleted": safe}
