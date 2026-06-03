#!/usr/bin/env python3
"""
fetch_invest_docs.py
~~~~~~~~~~~~~~~~~~~~
Scrapes https://invest.readthedocs.io/en/latest/models.html and writes
invest_docs_cache.json next to this script.

The cache is consumed by nan_to_mcp.py to generate authoritative, official
docstrings for every @mcp.tool() function it produces.

Usage
-----
    python fetch_invest_docs.py              # fetch & write cache
    python fetch_invest_docs.py --check      # show cache summary without re-fetching

Requirements
------------
    pip install requests beautifulsoup4
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MODELS_URL = "https://invest.readthedocs.io/en/latest/models.html"
CACHE_FILE = Path(__file__).parent / "invest_docs_cache.json"

# Map each section id (as it appears in the HTML anchor) → the function_name
# used in Nan/Shubham's code.  Only entries here will be extracted.
SECTION_TO_FUNCTION: dict[str, str] = {
    # already in Shubham's server — include so the cache is complete
    "annual-water-yield":                   "run_annual_water_yield",
    "carbon-storage-and-sequestration":     "run_carbon_storage",
    "coastal-blue-carbon":                  "run_coastal_blue_carbon",
    "coastal-blue-carbon-preprocessor":     "run_coastal_blue_carbon_preprocessor",
    "crop-production-percentile":           "run_crop_production_percentile",
    "crop-production-regression":           "run_crop_production_regression",
    "crop-pollination":                     "run_pollination",
    "forest-carbon-edge-effect":            "run_forest_carbon_edge_effect",
    "habitat-quality":                      "run_habitat_quality",
    "habitat-risk-assessment":              "run_habitat_risk_assessment",
    "nutrient-delivery-ratio":              "run_nutrient_delivery_ratio",
    "sediment-delivery-ratio":              "run_sediment_delivery_ratio",
    "seasonal-water-yield":                 "run_seasonal_water_yield",
    "visitation-recreation-and-tourism":    "run_recreation",
    # new models (Nan's 15)
    "coastal-vulnerability":                "run_coastal_vulnerability",
    "delineateit":                          "run_delineateit",
    "routedem":                             "run_routedem",
    "scenic-quality":                       "run_scenic_quality",
    "scenario-generator-proximity-based":   "run_scenario_gen_proximity",
    "urban-cooling":                        "run_urban_cooling",
    "urban-flood-risk-mitigation":          "run_urban_flood",
    "urban-mental-health":                  "run_urban_mental_health",
    "urban-nature-access":                  "run_urban_nature_access",
    "urban-stormwater-retention":           "run_urban_stormwater",
    "wave-energy-production":               "run_wave_energy",
    "wind-energy-production":               "run_offshore_wind_energy",
}


# ---------------------------------------------------------------------------
# HTML scraping helpers
# ---------------------------------------------------------------------------

def _fetch_html(url: str) -> str:
    try:
        import requests
    except ImportError:
        sys.exit(
            "ERROR: 'requests' is not installed.\n"
            "  pip install requests beautifulsoup4\n"
            "  (or: conda install requests beautifulsoup4)"
        )
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def _parse_models_page(html: str) -> dict[str, dict]:
    """Parse models.html and return {function_name: {description, params}}.

    HTML structure (readthedocs Sphinx autodoc):

        <section id="coastal-vulnerability">
          <h2>Coastal Vulnerability</h2>
          <dl class="py function">
            <dt class="sig sig-object py">
              <span class="sig-prename">natcap.invest.coastal_vulnerability.coastal_vulnerability.</span>
              <span class="sig-name descname">execute</span>(args)
            </dt>
            <dd>
              <p>Coastal Vulnerability.</p>
              <p>For points along a coastline ...</p>   ← model description
              <dl class="field-list simple">
                <dt class="field-odd">Parameters:</dt>
                <dd class="field-odd">
                  <ul class="simple">
                    <li><p>
                      <strong>args['aoi_vector_path']</strong> (<em>string</em>)
                      – path to a polygon vector ...    ← param description
                    </p></li>
                  </ul>
                </dd>
              </dl>
            </dd>
          </dl>
        </section>
    """
    try:
        from bs4 import BeautifulSoup, NavigableString
    except ImportError:
        sys.exit(
            "ERROR: 'beautifulsoup4' is not installed.\n"
            "  pip install requests beautifulsoup4"
        )

    soup = BeautifulSoup(html, "html.parser")
    results: dict[str, dict] = {}

    # Regex to extract param name from text like  args [ 'workspace_dir' ]
    # (get_text inserts spaces around every tag so brackets/quotes are separated)
    _ARG_RE = re.compile(r"""args\s*\[\s*['"]\s*([a-z_][a-z0-9_]*)\s*['"]\s*\]""")
    # Em-dash separator between type hint and description
    _EMDASH_RE = re.compile(r"\s*[–—]\s*")

    for anchor_id, fn_name in SECTION_TO_FUNCTION.items():
        section = soup.find(id=anchor_id) or soup.find(id=anchor_id.replace("-", "_"))
        if section is None:
            print(f"  [WARN] #{anchor_id} not found", file=sys.stderr)
            continue

        # Walk up to the <section> container
        container = section
        while container and container.name != "section":
            container = container.parent
        if container is None:
            container = section

        # ── Model description ─────────────────────────────────────────────
        # Lives in <p> tags inside the <dd> right after the <dt class="sig">
        description_parts: list[str] = []
        py_fn_dl = container.find("dl", class_="py")
        if py_fn_dl:
            fn_dd = py_fn_dl.find("dd")
            if fn_dd:
                for child in fn_dd.children:
                    if not hasattr(child, "name"):
                        continue
                    if child.name == "dl":   # reached the field-list → stop
                        break
                    if child.name == "p":
                        txt = child.get_text(" ", strip=True)
                        # Skip one-word titles like "Coastal Vulnerability."
                        if txt and len(txt.split()) > 3:
                            description_parts.append(txt)

        description = re.sub(r"\s+", " ", " ".join(description_parts)).strip()

        # ── Parameter descriptions ────────────────────────────────────────
        # Each <li> looks like:
        #   <strong>args['param_name']</strong> (<em>type</em>) – description text
        params: dict[str, str] = {}

        # Two param formats exist in the docs:
        #
        # Format A (most models) — args key split across multiple <strong> tags:
        #   args [ 'workspace_dir' ] ( string ) – description
        #
        # Format B (wave/wind energy) — bare name with no args[] wrapper:
        #   workspace_dir ( str ) – description
        #
        for li in container.find_all("li"):
            p_tag = li.find("p")
            if p_tag is None:
                continue
            full_text = re.sub(r"\s+", " ", p_tag.get_text(" ", strip=True))

            # Try Format A first
            m = _ARG_RE.search(full_text)
            if m:
                param_name = m.group(1)
                # Strip the "args [ 'x' ] ( type )" prefix before the em-dash
                parts = _EMDASH_RE.split(full_text, maxsplit=1)
                desc = parts[1].strip() if len(parts) == 2 else ""
            else:
                # Try Format B: bare "param_name ( type ) – description"
                m2 = re.match(
                    r"^([a-z_][a-z0-9_]*)\s*\([^)]*\)\s*[–—]\s*(.*)",
                    full_text, re.DOTALL,
                )
                if not m2:
                    continue
                param_name = m2.group(1)
                desc = m2.group(2).strip()

            # Remove leading "(required)" / "(optional)" qualifiers
            desc = re.sub(r"^\((required|optional)\)\s*", "", desc, flags=re.I).strip()
            desc = re.sub(r"\s+", " ", desc).strip().strip('"').strip("'")

            if desc and param_name:
                params[param_name] = desc[0].upper() + desc[1:]

        results[fn_name] = {"description": description, "params": params}

        summary = description[:70] + "..." if description else "(no description)"
        print(
            f"  [ok]  {fn_name:45s}  {len(params):3d} params  {summary}",
            file=sys.stderr,
        )

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="Print a summary of the existing cache without re-fetching.",
    )
    parser.add_argument(
        "--url", default=MODELS_URL,
        help=f"URL to fetch (default: {MODELS_URL})",
    )
    parser.add_argument(
        "--out", default=str(CACHE_FILE),
        help=f"Output JSON path (default: {CACHE_FILE})",
    )
    args = parser.parse_args()

    out_path = Path(args.out)

    if args.check:
        if not out_path.exists():
            sys.exit(f"Cache not found: {out_path}")
        cache = json.loads(out_path.read_text())
        print(f"Cache: {out_path}")
        print(f"Models: {len(cache)}")
        for fn, data in sorted(cache.items()):
            p = len(data.get("params", {}))
            d = data.get("description", "")[:70]
            print(f"  {fn:45s}  {p:3d} params  {d}")
        return

    print(f"Fetching {args.url} ...", file=sys.stderr)
    html = _fetch_html(args.url)
    print(f"  Downloaded {len(html):,} bytes", file=sys.stderr)

    print("Parsing model sections ...", file=sys.stderr)
    cache = _parse_models_page(html)

    out_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
    print(
        f"\n[done] Wrote {len(cache)} models to {out_path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
