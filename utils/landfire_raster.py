"""LANDFIRE EVT raster — download a clipped GeoTIFF for an AOI, then sample.

The existing utils/landfire.py uses ImageServer's `identify` endpoint for
single-point queries. For dense grid sampling (porcini candidate generation)
that's far too many API calls. This module uses the same ImageServer's
`exportImage` endpoint to download a clipped raster ONCE, then we sample it
locally at any density.

The download is a one-time cost; rasters are checked in to data/raster/ so
re-builds are free.
"""

from pathlib import Path

import rasterio
from rasterio.transform import xy as raster_xy

from utils.http import fetch_json


EVT_IMAGESERVER = (
    "https://lfps.usgs.gov/arcgis/rest/services/"
    "Landfire_LF2024/LF2024_EVT_CONUS/ImageServer"
)

# LF2020 topo rasters — elevation (m), aspect (degrees), slope (degrees)
TOPO_BASE = "https://lfps.usgs.gov/arcgis/rest/services/Landfire_Topo"
ELEV_IMAGESERVER  = f"{TOPO_BASE}/LF2020_Elev_CONUS/ImageServer"
ASPECT_IMAGESERVER = f"{TOPO_BASE}/LF2020_Asp_CONUS/ImageServer"
SLOPE_IMAGESERVER = f"{TOPO_BASE}/LF2020_SlpD_CONUS/ImageServer"


def _download_raster(image_server, bbox, output_path, resolution_m,
                     pixel_type, interpolation, label):
    """Generic LANDFIRE ImageServer raster download via exportImage."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    min_lon, min_lat, max_lon, max_lat = bbox

    import math
    mid_lat = (min_lat + max_lat) / 2
    height_m = (max_lat - min_lat) * 111_000
    width_m = (max_lon - min_lon) * 111_000 * math.cos(math.radians(mid_lat))
    width_px = int(width_m / resolution_m)
    height_px = int(height_m / resolution_m)

    cap = 4000
    if width_px > cap or height_px > cap:
        scale = max(width_px / cap, height_px / cap)
        width_px = int(width_px / scale)
        height_px = int(height_px / scale)
        print(f"  {label}: bbox too big at {resolution_m}m — scaled to {width_px}x{height_px}")

    params = {
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "bboxSR": "4326",
        "imageSR": "4326",
        "size": f"{width_px},{height_px}",
        "format": "tiff",
        "pixelType": pixel_type,
        "interpolation": interpolation,
        "f": "image",
    }

    import requests
    url = f"{image_server}/exportImage"
    print(f"  {label}: downloading {width_px}x{height_px} for bbox {bbox}")
    r = requests.get(url, params=params, timeout=180)
    r.raise_for_status()
    if not r.headers.get("Content-Type", "").startswith("image"):
        raise RuntimeError(f"expected image, got {r.headers.get('Content-Type')}: {r.text[:300]}")
    output_path.write_bytes(r.content)
    size_kb = output_path.stat().st_size / 1024
    print(f"  {label}: wrote {output_path} ({size_kb:.0f}KB)")
    return output_path


def download_evt_raster(bbox, output_path, resolution_m=30):
    """Categorical EVT raster — never interpolate."""
    return _download_raster(
        EVT_IMAGESERVER, bbox, output_path, resolution_m,
        pixel_type="U16", interpolation="RSP_NearestNeighbor", label="EVT")


def download_elevation_raster(bbox, output_path, resolution_m=100):
    """LANDFIRE elevation in meters. Bilinear is fine for continuous data."""
    return _download_raster(
        ELEV_IMAGESERVER, bbox, output_path, resolution_m,
        pixel_type="S16", interpolation="RSP_BilinearInterpolation", label="ELEV")


def download_aspect_raster(bbox, output_path, resolution_m=100):
    """LANDFIRE aspect in degrees clockwise from north (0–360, -1 for flat)."""
    return _download_raster(
        ASPECT_IMAGESERVER, bbox, output_path, resolution_m,
        pixel_type="S16", interpolation="RSP_NearestNeighbor", label="ASPECT")


def download_slope_raster(bbox, output_path, resolution_m=100):
    """LANDFIRE slope in degrees (0–90)."""
    return _download_raster(
        SLOPE_IMAGESERVER, bbox, output_path, resolution_m,
        pixel_type="U8", interpolation="RSP_BilinearInterpolation", label="SLOPE")


def sample_at(raster_path, lat, lon):
    """Read raster value at a single (lat, lon). Returns None on miss."""
    with rasterio.open(raster_path) as src:
        try:
            row, col = src.index(lon, lat)
            if 0 <= row < src.height and 0 <= col < src.width:
                return src.read(1)[row, col]
        except Exception:
            pass
    return None


def iter_evt_grid(raster_path, stride=1):
    """
    Iterate (lat, lon, evt_code) for every pixel in the raster.

    `stride` skips pixels — stride=3 samples every 3rd pixel in each dimension.
    For a 30m raster, stride=3 ≈ 90m sampling; stride=1 = native 30m.
    """
    with rasterio.open(raster_path) as src:
        # CRS is EPSG:4326 (WGS84) since we requested it. Transform converts
        # pixel (row, col) → (lon, lat).
        band = src.read(1)
        height, width = band.shape
        transform = src.transform
        for row in range(0, height, stride):
            for col in range(0, width, stride):
                code = int(band[row, col])
                if code == 0:
                    continue  # NoData
                lon, lat = raster_xy(transform, row, col)
                yield lat, lon, code


def evt_pixel_count_by_code(raster_path):
    """Diagnostic: count pixels of each EVT code in the raster."""
    counts = {}
    with rasterio.open(raster_path) as src:
        band = src.read(1)
        unique, freq = _unique_counts(band)
        for code, n in zip(unique, freq):
            if code != 0:
                counts[int(code)] = int(n)
    return counts


def _unique_counts(arr):
    """numpy.unique with return_counts, isolated for testing."""
    import numpy as np
    return np.unique(arr, return_counts=True)
