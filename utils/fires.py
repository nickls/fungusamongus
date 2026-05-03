"""Fire perimeter and fuel treatment data sources."""

from datetime import datetime

from utils.cache import cache_key, cache_get, cache_set
from utils.http import fetch_json
from config import CACHE_TTL_FIRE_HOURS

RX_KEYWORDS = {"burn", "rx", "prescribed", "pile", "underburn", "broadcast", "fire", "ignit"}


def get_recent_fires(center_lat: float, center_lon: float,
                     radius_km: float = 70) -> list[dict]:
    """
    Query NIFC Interagency Fire Perimeter History (public, no auth).
    Only reliable free federal fire perimeter API as of 2026.
    """
    key = cache_key("fires_nifc", lat=round(center_lat, 2), lon=round(center_lon, 2), r=radius_km)
    cached = cache_get(key, CACHE_TTL_FIRE_HOURS)
    if cached:
        print(f"  [cached] {len(cached)} NIFC fire perimeters")
        return cached

    fires = []
    deg = radius_km / 111.0
    envelope = f"{center_lon-deg},{center_lat-deg},{center_lon+deg},{center_lat+deg}"
    url = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services"
           "/InteragencyFirePerimeterHistory_All_Years_View/FeatureServer/0/query")

    current_year = datetime.now().year
    print(f"  Querying NIFC Interagency Fire History ({current_year-3}+)...")
    offset = 0
    while True:
        data = fetch_json(url, {
            "geometry": envelope,
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": "4326", "outSR": "4326",
            "where": f"FIRE_YEAR_INT >= {current_year - 4}",
            "outFields": "INCIDENT,GIS_ACRES,DATE_CUR,FIRE_YEAR_INT,AGENCY,SOURCE,FEATURE_CA,COMMENTS",
            "returnGeometry": "true", "f": "json",
            "resultRecordCount": 2000,
            "resultOffset": offset,
        }, timeout=60)

        if not data or "features" not in data or not data["features"]:
            break

        for feat in data["features"]:
            a = feat.get("attributes", {})
            g = feat.get("geometry", {})
            name = a.get("INCIDENT") or "Unknown"
            acres = float(a.get("GIS_ACRES") or 0)
            year = a.get("FIRE_YEAR_INT")
            feature_cat = (a.get("FEATURE_CA") or "").lower()

            fire_date = None
            dc = a.get("DATE_CUR")
            if dc and len(str(dc)) >= 8:
                try:
                    fire_date = f"{str(dc)[:4]}-{str(dc)[4:6]}-{str(dc)[6:8]}"
                except (IndexError, ValueError):
                    pass

            is_rx = ("prescribed" in feature_cat or "rx" in feature_cat
                     or "prescribed" in name.lower() or "rx " in name.lower())

            clat, clon = None, None
            if "rings" in g and g["rings"] and g["rings"][0]:
                ring = g["rings"][0]
                clon = sum(p[0] for p in ring) / len(ring)
                clat = sum(p[1] for p in ring) / len(ring)

            fires.append({
                "name": name, "source": "NIFC", "acres": acres,
                "date": fire_date, "year": str(year) if year else None,
                "is_rx": is_rx, "is_treatment": False,
                "centroid_lat": clat, "centroid_lon": clon,
                "geometry": g if g else None,
            })

        if not data.get("exceededTransferLimit"):
            break
        offset += len(data["features"])

    rx_ct = sum(1 for f in fires if f["is_rx"])
    print(f"  Found {len(fires)} fire perimeters ({rx_ct} prescribed, {len(fires)-rx_ct} wildfire)")
    cache_set(key, fires)
    return fires


def get_tahoe_fuels_treatments(center_lat, center_lon, radius_km=80):
    key = cache_key("fuels", lat=round(center_lat, 2), lon=round(center_lon, 2), r=radius_km)
    cached = cache_get(key, CACHE_TTL_FIRE_HOURS)
    if cached:
        print(f"  [cached] {len(cached)} fuel treatments")
        return cached

    fires = []
    deg = radius_km / 111.0
    envelope = f"{center_lon-deg},{center_lat-deg},{center_lon+deg},{center_lat+deg}"
    url = ("https://services6.arcgis.com/1KtlSd2mklZMBKaz/arcgis/rest/services"
           "/Tahoe_Forest_Fuels_Tx_OFFICIAL_Public_View/FeatureServer/0/query")

    current_year = datetime.now().year
    print("  Querying Tahoe Forest Fuels Treatments...")

    offset = 0
    while True:
        data = fetch_json(url, {
            "geometry": envelope,
            "geometryType": "esriGeometryEnvelope",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": "4326", "outSR": "4326",
            "where": f"YEAR >= {current_year - 4}",
            "outFields": "ACT,YEAR,ACRES,CATEGORY,PROJ,FuelsTx",
            "returnGeometry": "true", "f": "json",
            "resultRecordCount": 2000,
            "resultOffset": offset,
        }, timeout=60)

        if not data or "features" not in data or not data["features"]:
            break

        for feat in data["features"]:
            a = feat.get("attributes", {})
            g = feat.get("geometry", {})
            act = (a.get("ACT") or "").lower()
            year = a.get("YEAR")
            acres = float(a.get("ACRES") or 0)
            is_burn = any(kw in act for kw in RX_KEYWORDS)

            clat, clon = None, None
            if "rings" in g and g["rings"] and g["rings"][0]:
                ring = g["rings"][0]
                clon = sum(p[0] for p in ring) / len(ring)
                clat = sum(p[1] for p in ring) / len(ring)

            name = f"{a.get('PROJ', '?')} -- {a.get('ACT', '?')}"
            fires.append({
                "name": name, "source": "Tahoe Fuels Tx",
                "acres": acres, "date": f"{year}-01-15" if year else None,
                "year": str(year) if year else None,
                "is_rx": is_burn, "is_treatment": True,
                "activity": act, "category": (a.get("CATEGORY") or "").lower(),
                "centroid_lat": clat, "centroid_lon": clon,
                "geometry": g if g else None,
            })

        if not data.get("exceededTransferLimit"):
            break
        offset += len(data["features"])

    burn_count = sum(1 for f in fires if f["is_rx"])
    print(f"  Found {len(fires)} fuel treatments ({burn_count} burns, {len(fires) - burn_count} mechanical)")
    cache_set(key, fires)
    return fires
