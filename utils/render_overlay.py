"""
Render a per-species suitability PNG overlay from the LANDFIRE EVT raster.

For each pixel of the raster, look up the EVT code's suitability for the
species; pixels below threshold get transparent, others get tinted by
suitability score on a gray → orange → green → purple gradient. Saves a
PNG sized to match the raster's bbox so it can be dropped on the map as a
Leaflet ImageOverlay.

This is one-time rendering — the suitability per pixel is biological
constant, not weather-dependent. Re-run only when the raster changes.

Run:
    python -m utils.render_overlay porcini
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

from utils.landfire import EVT_LOOKUP


# Suitability thresholds per species. Anything ≥ threshold is rendered.
SPECIES_THRESHOLDS = {
    "porcini": 0.5,
    "morel":   0.5,  # for completeness, though morel doesn't use this overlay
}

# Color gradient — matches popup.js scoreColor() so the overlay and
# diamond markers share a visual language.
def color_for_score(score):
    """Return (r, g, b, a) for a 0..1 score. Transparent when score=0."""
    if score <= 0:
        return (0, 0, 0, 0)
    if score < 0.6:
        # gray → orange (0.5–0.6 band)
        return (0xa0, 0x60, 0x20, 100)
    if score < 0.75:
        return (0xe6, 0x7e, 0x22, 130)  # orange
    if score < 0.9:
        return (0x27, 0xae, 0x60, 150)  # green
    return (0x9b, 0x59, 0xb6, 170)      # purple — top suitability


def render(species, raster_path, output_path):
    threshold = SPECIES_THRESHOLDS.get(species)
    if threshold is None:
        print(f"ERROR: unknown species '{species}'", file=sys.stderr)
        sys.exit(2)

    print(f"  reading {raster_path}")
    with rasterio.open(raster_path) as src:
        evt = src.read(1)
        bounds = src.bounds  # actual georeferenced bounds
        print(f"  raster {evt.shape[1]}x{evt.shape[0]} px, {evt.size} pixels")
        print(f"  bounds: lat [{bounds.bottom:.4f}, {bounds.top:.4f}] "
              f"lon [{bounds.left:.4f}, {bounds.right:.4f}]")

    # Build LUT mapping EVT code -> RGBA. Default = transparent.
    max_code = int(evt.max()) + 1
    lut = np.zeros((max_code, 4), dtype=np.uint8)
    suitable_count = 0
    for code, (_, suit) in EVT_LOOKUP.items():
        if suit >= threshold and code < max_code:
            r, g, b, a = color_for_score(suit)
            lut[code] = (r, g, b, a)
            suitable_count += 1
    print(f"  {suitable_count} EVT codes ≥ {threshold} suitability")

    # Apply LUT — bound check first
    safe_evt = np.clip(evt, 0, max_code - 1)
    rgba = lut[safe_evt]
    suitable_pixels = int((rgba[..., 3] > 0).sum())
    print(f"  {suitable_pixels:,} pixels colored "
          f"({100 * suitable_pixels / evt.size:.1f}% of raster)")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # The raster only uses ~5 distinct colors; palette mode shrinks this
    # dramatically. Quantize on RGBA requires Fast Octree (method=2).
    rgba_img = Image.fromarray(rgba, mode="RGBA")
    palette_img = rgba_img.quantize(colors=8, method=Image.Quantize.FASTOCTREE)
    palette_img.save(output_path, optimize=True)
    size_kb = output_path.stat().st_size / 1024
    print(f"  wrote {output_path} ({size_kb:.0f}KB, palette)")

    # Sidecar JSON with the actual raster bounds — ArcGIS exportImage expands
    # the bbox to preserve pixel aspect, so the requested bbox != real bbox.
    # The SPA reads this to position the Leaflet ImageOverlay correctly.
    import json
    sidecar = output_path.with_suffix(".json")
    sidecar.write_text(json.dumps({
        "bounds": {
            "south": bounds.bottom,
            "north": bounds.top,
            "west": bounds.left,
            "east": bounds.right,
        },
        "leaflet_bounds": [[bounds.bottom, bounds.left], [bounds.top, bounds.right]],
    }, indent=2))
    print(f"  wrote {sidecar}")


def main():
    parser = argparse.ArgumentParser(description="Render species suitability overlay PNG")
    parser.add_argument("species", choices=list(SPECIES_THRESHOLDS.keys()))
    parser.add_argument("--raster", default="data/raster/tahoe_evt.tif")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    raster_path = Path(args.raster)
    if not raster_path.exists():
        print(f"ERROR: {raster_path} not found — run build_porcini_sites.py --fetch-raster",
              file=sys.stderr)
        sys.exit(2)
    output_path = Path(args.output) if args.output else Path(f"docs/data/{args.species}-overlay.png")
    render(args.species, raster_path, output_path)


if __name__ == "__main__":
    main()
