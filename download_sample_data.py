"""
Download official NatCap InVEST sample data and QGIS test data.

Usage:
    python download_sample_data.py            # download everything
    python download_sample_data.py --invest   # InVEST only
    python download_sample_data.py --qgis     # QGIS only
    python download_sample_data.py --dry-run  # show what would be downloaded

Downloads:
  InVEST  → backend/data/sample-inputs/<ModelName>/
  QGIS    → mcp-servers/qgis-mcp/data/

After downloading, run:
    cd backend && pytest tests/ -v --timeout=300
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR  = Path(__file__).parent
INVEST_DIR  = SCRIPT_DIR / "backend" / "data" / "sample-inputs"
QGIS_DIR    = SCRIPT_DIR / "mcp-servers" / "qgis-mcp" / "data"

INVEST_VERSION = "3.18.0"
GCS_BASE = f"https://storage.googleapis.com/releases.naturalcapitalproject.org/invest/{INVEST_VERSION}/data"

# ---------------------------------------------------------------------------
# InVEST datasets
# Each entry: (zip_filename, target_subdir_inside_sample-inputs)
# The zip extracts to a folder with the same name as the zip (NatCap convention).
# ---------------------------------------------------------------------------

INVEST_DATASETS = [
    # (zip name on GCS,            local folder name under sample-inputs/)
    ("Carbon.zip",                  "Carbon"),
    ("HabitatQuality.zip",          "HabitatQuality"),
    ("Annual_Water_Yield.zip",      "AnnualWaterYield"),
    ("pollination.zip",             "Pollination"),
    ("SDR.zip",                     "SDR"),
    ("NDR.zip",                     "NDR"),
    ("forest_carbon_edge_effect.zip", "ForestCarbonEdge"),
    ("CoastalBlueCarbon.zip",       "CoastalBlueCarbon"),
    ("Seasonal_Water_Yield.zip",    "SeasonalWaterYield"),
    ("CropProduction.zip",          "CropProduction"),
    ("HabitatRiskAssess.zip",       "HabitatRiskAssess"),
    ("recreation.zip",              "Recreation"),
]

# ---------------------------------------------------------------------------
# QGIS datasets
# ---------------------------------------------------------------------------

QGIS_DATASETS = [
    {
        "name": "QGIS Alaska sample data",
        "url": "https://github.com/qgis/QGIS-Sample-Data/archive/master.zip",
        "extract_subdir": "QGIS-Sample-Data-master",  # top-level folder inside zip
        "target": QGIS_DIR / "alaska",
    },
    {
        "name": "Natural Earth 110m countries (GeoJSON)",
        "url": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson",
        "target": QGIS_DIR / "ne_110m_admin_0_countries.geojson",
        "single_file": True,
    },
    {
        "name": "GDAL utmsmall.tif (100×100 px, NAD27/UTM)",
        "url": "https://github.com/OSGeo/gdal/raw/master/autotest/gcore/data/utmsmall.tif",
        "target": QGIS_DIR / "utmsmall.tif",
        "single_file": True,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar(downloaded: int, total: int, width: int = 40) -> str:
    if total <= 0:
        return f"  {downloaded // 1024} KB"
    pct   = downloaded / total
    filled = int(width * pct)
    bar   = "█" * filled + "░" * (width - filled)
    return f"  [{bar}] {pct*100:5.1f}%  {downloaded//1024:,} / {total//1024:,} KB"


def download_bytes(url: str, label: str) -> bytes:
    print(f"  Downloading {label} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "telecoupling-data-downloader/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        buf   = io.BytesIO()
        chunk = 65536
        while True:
            data = resp.read(chunk)
            if not data:
                break
            buf.write(data)
            print(f"\r{_bar(buf.tell(), total)}", end="", flush=True)
    print()
    return buf.getvalue()


def extract_zip(data: bytes, dest: Path, strip_top: str | None = None) -> None:
    """Extract zip bytes to dest, optionally stripping a top-level directory prefix."""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.infolist():
            name = member.filename
            if strip_top:
                # Remove the top-level folder from the path
                parts = Path(name).parts
                if len(parts) <= 1:
                    continue  # skip the top-level dir entry itself
                name = str(Path(*parts[1:]))
            target = dest / name
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as f:
                    shutil.copyfileobj(src, f)


# ---------------------------------------------------------------------------
# InVEST downloader
# ---------------------------------------------------------------------------

def download_invest(dry_run: bool = False) -> None:
    print("\n" + "=" * 60)
    print(f"  InVEST {INVEST_VERSION} sample data  →  {INVEST_DIR}")
    print("=" * 60)

    INVEST_DIR.mkdir(parents=True, exist_ok=True)

    for zip_name, local_name in INVEST_DATASETS:
        dest = INVEST_DIR / local_name
        url  = f"{GCS_BASE}/{zip_name}"

        if dest.exists():
            existing = sum(1 for _ in dest.rglob("*") if _.is_file())
            print(f"\n[SKIP] {local_name}/ already exists ({existing} files). Delete to re-download.")
            continue

        print(f"\n[GET]  {zip_name}  →  {dest.name}/")
        if dry_run:
            print(f"       {url}")
            continue

        data = download_bytes(url, zip_name)
        print(f"  Extracting ...")

        # NatCap zips extract to a folder named after the zip (without extension),
        # but names vary — detect the actual top-level folder from the zip itself.
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            tops = {Path(n).parts[0] for n in zf.namelist() if n.strip("/")}
            top_dir = tops.pop() if len(tops) == 1 else None

        if top_dir:
            # Extract into a private temp dir, then move to canonical dest.
            # Never use extractall(INVEST_DIR) — that leaves residue at the root.
            tmp_root = INVEST_DIR / f"_dl_tmp_{local_name}"
            if tmp_root.exists():
                shutil.rmtree(tmp_root)
            tmp_root.mkdir(parents=True)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(tmp_root)          # → tmp_root/<top_dir>/...
            extracted = tmp_root / top_dir
            if dest.exists():
                shutil.rmtree(dest)
            extracted.rename(dest)               # move <top_dir>/ → <local_name>/
            shutil.rmtree(tmp_root, ignore_errors=True)
        else:
            extract_zip(data, dest)

        n_files = sum(1 for _ in dest.rglob("*") if _.is_file())
        print(f"  Done — {n_files} files in {dest}")

    print(f"\n InVEST sample data complete.\n")


# ---------------------------------------------------------------------------
# QGIS downloader
# ---------------------------------------------------------------------------

def download_qgis(dry_run: bool = False) -> None:
    print("\n" + "=" * 60)
    print(f"  QGIS sample data  →  {QGIS_DIR}")
    print("=" * 60)

    QGIS_DIR.mkdir(parents=True, exist_ok=True)

    for ds in QGIS_DATASETS:
        name   = ds["name"]
        url    = ds["url"]
        target = ds["target"]

        if target.exists():
            print(f"\n[SKIP] {target.name} already exists.")
            continue

        print(f"\n[GET]  {name}")
        if dry_run:
            print(f"       {url}")
            continue

        data = download_bytes(url, name)

        if ds.get("single_file"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            print(f"  Saved → {target.name}  ({len(data)//1024:,} KB)")
        else:
            # Zip — extract and strip top-level folder
            strip = ds.get("extract_subdir")
            print(f"  Extracting ...")
            extract_zip(data, target, strip_top=strip)
            n = sum(1 for _ in target.rglob("*") if _.is_file())
            print(f"  Done — {n} files in {target}")

    print(f"\n QGIS sample data complete.\n")


# ---------------------------------------------------------------------------
# conftest.py path updater
# ---------------------------------------------------------------------------

# Maps: local folder name → dict of {fixture_variable: relative_path_from_model_dir}
# These are derived from the .invs.json files in each NatCap zip.
INVEST_ARGS = {
    "Carbon": {
        "_lulc_cur_path":       "lulc_current_willamette.tif",
        "_carbon_pools_path":   "carbon_pools_willamette.csv",
        "_lulc_fut_path":       "lulc_future_willamette.tif",
    },
    "HabitatQuality": {
        "_lulc_cur_path":           "lulc_current_willamette.tif",
        "_lulc_fut_path":           "lulc_future_willamette.tif",
        "_threats_table_path":      "threats_willamette.csv",
        "_sensitivity_table_path":  "sensitivity_willamette.csv",
        "_access_vector_path":      "accessibility_willamette.shp",
    },
    "AnnualWaterYield": {
        "_lulc_path":                       "land_use_gura.tif",
        "_depth_to_root_rest_layer_path":   "depth_to_root_restricting_layer_gura.tif",
        "_precipitation_path":              "precipitation_gura.tif",
        "_pawc_path":                       "plant_available_water_fraction_gura.tif",
        "_eto_path":                        "reference_ET_gura.tif",
        "_watersheds_path":                 "watershed_gura.shp",
        "_biophysical_table_path":          "biophysical_table_gura.csv",
    },
    "Pollination": {
        "_landcover_raster_path":           "landcover.tif",
        "_guild_table_path":                "guild_table.csv",
        "_landcover_biophysical_table_path":"landcover_biophysical_table.csv",
    },
    "SDR": {
        "_dem_path":                "DEM_gura.tif",
        "_erosivity_path":          "erosivity_gura.tif",
        "_erodibility_path":        "erodibility_gura.tif",
        "_lulc_path":               "land_use_gura.tif",
        "_watersheds_path":         "watershed_gura.shp",
        "_biophysical_table_path":  "biophysical_table_Gura.csv",
    },
    "NDR": {
        "_dem_path":                "DEM_gura.tif",
        "_lulc_path":               "land_use_gura.tif",
        "_runoff_proxy_path":       "precipitation_gura.tif",
        "_watersheds_path":         "watershed_gura.shp",
        "_biophysical_table_path":  "biophysical_table_gura.csv",
    },
    "ForestCarbonEdge": {
        "_lulc_raster_path":        "forest_carbon_edge_lulc_demo.tif",
        "_biophysical_table_path":  "forest_edge_carbon_lu_table.csv",
        "_tropical_model_path":     "core_data/forest_carbon_edge_regression_model_parameters.shp",
    },
}


def update_conftest(dry_run: bool = False) -> None:
    conftest = Path(__file__).parent / "backend" / "tests" / "conftest.py"
    if not conftest.exists():
        print(f"[WARN] conftest.py not found at {conftest}")
        return

    print("\n" + "=" * 60)
    print("  Updating conftest.py with real NatCap file paths")
    print("=" * 60)

    text = conftest.read_text()
    original = text

    base = INVEST_DIR

    # --- Carbon Storage fixture ---
    d = base / "Carbon"
    text = _replace_fixture_block(
        text, "carbon_run_result",
        f'f"Run carbon storage analysis using these exact paths: '
        f'lulc_cur_path={d}/lulc_current_willamette.tif, '
        f'carbon_pools_path={d}/carbon_pools_willamette.csv"',
    )

    # --- Habitat Quality fixture ---
    d = base / "HabitatQuality"
    text = _replace_fixture_block(
        text, "hq_run_result",
        f'f"Run habitat quality analysis with: '
        f'lulc_cur_path={d}/lulc_current_willamette.tif, '
        f'lulc_fut_path={d}/lulc_future_willamette.tif, '
        f'threats_table_path={d}/threats_willamette.csv, '
        f'sensitivity_table_path={d}/sensitivity_willamette.csv, '
        f'access_vector_path={d}/accessibility_willamette.shp, '
        f'half_saturation_constant=0.05"',
    )

    # --- Annual Water Yield fixture ---
    d = base / "AnnualWaterYield"
    text = _replace_fixture_block(
        text, "awy_run_result",
        f'f"Run annual water yield model with: '
        f'lulc_path={d}/land_use_gura.tif, '
        f'depth_to_root_rest_layer_path={d}/depth_to_root_restricting_layer_gura.tif, '
        f'precipitation_path={d}/precipitation_gura.tif, '
        f'pawc_path={d}/plant_available_water_fraction_gura.tif, '
        f'eto_path={d}/reference_ET_gura.tif, '
        f'watersheds_path={d}/watershed_gura.shp, '
        f'biophysical_table_path={d}/biophysical_table_gura.csv, '
        f'seasonality_constant=5"',
    )

    # --- Pollination fixture ---
    d = base / "Pollination"
    text = _replace_fixture_block(
        text, "pollination_run_result",
        f'f"Run pollination model with: '
        f'landcover_raster_path={d}/landcover.tif, '
        f'guild_table_path={d}/guild_table.csv, '
        f'landcover_biophysical_table_path={d}/landcover_biophysical_table.csv"',
    )

    # --- SDR fixture ---
    d = base / "SDR"
    text = _replace_fixture_block(
        text, "sdr_run_result",
        f'f"Run sediment delivery ratio model with: '
        f'dem_path={d}/DEM_gura.tif, '
        f'erosivity_path={d}/erosivity_gura.tif, '
        f'erodibility_path={d}/erodibility_gura.tif, '
        f'lulc_path={d}/land_use_gura.tif, '
        f'watersheds_path={d}/watershed_gura.shp, '
        f'biophysical_table_path={d}/biophysical_table_Gura.csv, '
        f'threshold_flow_accumulation=1000, k_param=2, sdr_max=0.8, '
        f'ic_0_param=0.5, l_max=122"',
    )

    # --- NDR fixture ---
    d = base / "NDR"
    text = _replace_fixture_block(
        text, "ndr_run_result",
        f'f"Run nutrient delivery ratio model with: '
        f'dem_path={d}/DEM_gura.tif, '
        f'lulc_path={d}/land_use_gura.tif, '
        f'runoff_proxy_path={d}/precipitation_gura.tif, '
        f'watersheds_path={d}/watershed_gura.shp, '
        f'biophysical_table_path={d}/biophysical_table_gura.csv, '
        f'calc_p=true, calc_n=true, threshold_flow_accumulation=1000, '
        f'k_param=2, subsurface_critical_length_n=200, subsurface_eff_n=0.8"',
    )

    # --- Forest Carbon Edge fixture ---
    d = base / "ForestCarbonEdge"
    text = _replace_fixture_block(
        text, "fce_run_result",
        f'f"Run forest carbon edge effect model with: '
        f'lulc_raster_path={d}/forest_carbon_edge_lulc_demo.tif, '
        f'biophysical_table_path={d}/forest_edge_carbon_lu_table.csv, '
        f'tropical_forest_edge_carbon_model_vector_path='
        f'{d}/core_data/forest_carbon_edge_regression_model_parameters.shp, '
        f'n_nearest_model_points=10, biomass_to_carbon_conversion_factor=0.47, '
        f'pools_to_calculate=all, compute_forest_edge_effects=true"',
    )

    if text == original:
        print("  No changes needed — paths already up to date.")
        return

    if dry_run:
        print("  [DRY RUN] Would update conftest.py fixture content strings.")
        return

    conftest.write_text(text)
    print("  conftest.py updated with real NatCap file paths.")


def _replace_fixture_block(text: str, fixture_name: str, new_content_str: str) -> str:
    """No-op — conftest.py now auto-detects real vs synthetic paths at runtime."""
    return text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--invest",   action="store_true", help="Download InVEST sample data only")
    parser.add_argument("--qgis",     action="store_true", help="Download QGIS sample data only")
    parser.add_argument("--dry-run",  action="store_true", help="Show what would be downloaded, don't fetch")
    args = parser.parse_args()

    do_invest = args.invest or (not args.invest and not args.qgis)
    do_qgis   = args.qgis   or (not args.invest and not args.qgis)

    if args.dry_run:
        print("\n[DRY RUN] Nothing will be downloaded.\n")

    if do_invest:
        download_invest(dry_run=args.dry_run)

    if do_qgis:
        download_qgis(dry_run=args.dry_run)

    if not args.dry_run:
        print("\nAll downloads complete.")
        print("Next: update conftest.py fixture paths to point at real data,")
        print("      then run:  cd backend && pytest tests/ -v --timeout=300")


if __name__ == "__main__":
    main()
