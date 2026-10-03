from __future__ import annotations

import os
from datetime import date, timedelta
from functools import lru_cache
from threading import Lock
from time import monotonic
from typing import Any

SMAP_DATASET = "NASA/SMAP/SPL4SMGP/008"
S2_DATASET = "COPERNICUS/S2_HARMONIZED"
S1_DATASET = "COPERNICUS/S1_GRD"
GAUL_DATASET = "FAO/GAUL/2025/level2"
LATEST_SMAP_CACHE_TTL_SECONDS = 15 * 60
_latest_smap_cache_lock = Lock()
_latest_smap_cache: tuple[float, dict[str, Any]] | None = None


@lru_cache(maxsize=1)
def _earth_engine():
    project = os.getenv("GOOGLE_EARTH_ENGINE_PROJECT", "").strip()
    if not project:
        raise RuntimeError("Earth Engine is not configured: set GOOGLE_EARTH_ENGINE_PROJECT and authenticate service credentials.")
    try:
        import ee

        ee.Initialize(project=project)
        return ee
    except Exception as exc:
        raise RuntimeError("Earth Engine is not configured or authentication is unavailable.") from exc


def _mehsana_geometry(ee):
    areas = (
        ee.FeatureCollection(GAUL_DATASET)
        .filter(ee.Filter.eq("GAUL0_NAME", "India"))
        .filter(ee.Filter.eq("GAUL1_NAME", "Gujarat"))
        .filter(ee.Filter.Or(ee.Filter.eq("GAUL2_NAME", "Mehsana"), ee.Filter.eq("GAUL2_NAME", "Mahesana")))
    )
    if areas.size().getInfo() == 0:
        raise RuntimeError("Mehsana boundary was not found in the configured boundary collection.")
    return areas.geometry()


@lru_cache(maxsize=1)
def get_mehsana_boundary_geojson() -> dict[str, Any]:
    ee = _earth_engine()
    geometry = _mehsana_geometry(ee)
    boundary = geometry.simplify(1000).getInfo()
    return {
        "type": "Feature",
        "properties": {"name": "Mehsana District", "source": GAUL_DATASET},
        "geometry": boundary,
    }


@lru_cache(maxsize=32)
def get_real_observations(start_date: date | None, end_date: date | None) -> list[dict[str, Any]]:
    ee = _earth_engine()
    geometry = _mehsana_geometry(ee)
    end = end_date or date.today()
    start = start_date or end - timedelta(days=30)
    if start > end:
        return []
    if (end - start).days > 365:
        raise RuntimeError("SMAP history requests are limited to 366 days per request.")
    collection = (
        ee.ImageCollection(SMAP_DATASET)
        .filterBounds(geometry)
        .filterDate(start.isoformat(), (end + timedelta(days=1)).isoformat())
        .select("sm_surface")
    )
    first_day = ee.Date(start.isoformat())

    def daily_feature(offset):
        day = first_day.advance(ee.Number(offset), "day")
        daily = collection.filterDate(day, day.advance(1, "day"))
        image = ee.Image(
            ee.Algorithms.If(
                daily.size().gt(0),
                daily.mean(),
                ee.Image.constant(-999).rename("sm_surface"),
            )
        )
        mean = image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=11000,
            maxPixels=1_000_000,
            bestEffort=True,
            tileScale=2,
        )
        return ee.Feature(None, mean.set("date", day.format("YYYY-MM-dd")))

    day_count = (end - start).days + 1
    features = ee.FeatureCollection(ee.List.sequence(0, day_count - 1).map(daily_feature))
    response = features.getInfo()
    observations = []
    for feature in response.get("features", []):
        props = feature.get("properties", {})
        value = props.get("sm_surface")
        if value is None or value <= -900:
            continue
        observations.append({
            "date": props["date"],
            "latitude": 23.59,
            "longitude": 72.37,
            "soil_moisture": value,
            "rainfall_mm": None,
            "temperature_c": None,
            "ndvi": None,
            "ndmi": None,
            "ndwi": None,
            "evi": None,
            "savi": None,
            "et0_mm": None,
            "crop": None,
            "growth_stage": None,
            "moisture_stress": None,
            "irrigation_advisory": None,
            "source": f"NASA Earth Engine {SMAP_DATASET} · coarse regional observation",
            "data_mode": "REAL",
        })
    return observations


def sentinel2_index_collection(start: date, end: date, geometry=None):
    ee = _earth_engine()
    geom = geometry or _mehsana_geometry(ee)

    def add_indices(image):
        reflectance = image.select(["B2", "B3", "B4", "B8", "B11"]).multiply(0.0001)
        ndvi = reflectance.normalizedDifference(["B8", "B4"]).rename("NDVI")
        ndmi = reflectance.normalizedDifference(["B8", "B11"]).rename("NDMI")
        ndwi = reflectance.normalizedDifference(["B3", "B8"]).rename("NDWI")
        evi = reflectance.expression(
            "2.5 * ((nir - red) / (nir + 6 * red - 7.5 * blue + 1))",
            {"nir": reflectance.select("B8"), "red": reflectance.select("B4"), "blue": reflectance.select("B2")},
        ).rename("EVI")
        savi = reflectance.expression(
            "1.5 * ((nir - red) / (nir + red + 0.5))",
            {"nir": reflectance.select("B8"), "red": reflectance.select("B4")},
        ).rename("SAVI")
        return image.addBands([ndvi, ndmi, ndwi, evi, savi]).select(["NDVI", "NDMI", "NDWI", "EVI", "SAVI"])

    return (
        ee.ImageCollection(S2_DATASET)
        .filterBounds(geom)
        .filterDate(start.isoformat(), (end + timedelta(days=1)).isoformat())
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
        .map(add_indices)
    )


@lru_cache(maxsize=32)
def get_sentinel2_indices(start: date, end: date) -> list[dict[str, Any]]:
    ee = _earth_engine()
    geometry = _mehsana_geometry(ee)
    collection = sentinel2_index_collection(start, end, geometry).sort("system:time_start")

    def summarize(image):
        stats = image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=20,
            maxPixels=10_000_000,
            bestEffort=True,
            tileScale=2,
        )
        return ee.Feature(None, stats.set("date", ee.Date(image.get("system:time_start")).format("YYYY-MM-dd")))

    payload = collection.limit(100).map(summarize).getInfo()
    return [
        {
            **feature.get("properties", {}),
            "source": f"Sentinel-2 {S2_DATASET}; cloud-filtered regional index composite",
            "data_mode": "REAL",
        }
        for feature in payload.get("features", [])
        if feature.get("properties", {}).get("NDVI") is not None
    ]


def sentinel1_collection(start: date, end: date, geometry=None):
    ee = _earth_engine()
    geom = geometry or _mehsana_geometry(ee)
    return (
        ee.ImageCollection(S1_DATASET)
        .filterBounds(geom)
        .filterDate(start.isoformat(), (end + timedelta(days=1)).isoformat())
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
        .select(["VV", "VH"])
    )


@lru_cache(maxsize=32)
def get_sentinel1_observations(start: date, end: date) -> list[dict[str, Any]]:
    ee = _earth_engine()
    geometry = _mehsana_geometry(ee)
    collection = sentinel1_collection(start, end, geometry).sort("system:time_start")

    def summarize(image):
        stats = image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=20,
            maxPixels=10_000_000,
            bestEffort=True,
            tileScale=2,
        )
        return ee.Feature(None, stats.set("date", ee.Date(image.get("system:time_start")).format("YYYY-MM-dd")))

    payload = collection.limit(100).map(summarize).getInfo()
    return [
        {
            **feature.get("properties", {}),
            "source": f"Sentinel-1 {S1_DATASET}; microwave backscatter, not direct soil-moisture retrieval",
            "data_mode": "REAL",
        }
        for feature in payload.get("features", [])
        if feature.get("properties", {}).get("VV") is not None
    ]


@lru_cache(maxsize=64)
def get_map_layer(layer: str, selected_date: date) -> dict[str, Any]:
    ee = _earth_engine()
    geometry = _mehsana_geometry(ee)
    start = selected_date.isoformat()
    end = (selected_date + timedelta(days=1)).isoformat()
    palettes = ["#9b3d36", "#dc8b4b", "#f2d98d", "#b6cc79", "#438465"]
    if layer == "soil_moisture":
        image = (
            ee.ImageCollection(SMAP_DATASET)
            .filterBounds(geometry)
            .filterDate(start, end)
            .select("sm_surface")
            .mean()
            .clip(geometry)
        )
        visualization = {"min": 0.05, "max": 0.50, "palette": palettes}
        source = f"NASA Earth Engine {SMAP_DATASET} · coarse regional observation"
        unit = "m³/m³"
    elif layer in {"ndvi", "ndmi", "ndwi"}:
        band = layer.upper()
        window_start = selected_date - timedelta(days=30)
        collection = sentinel2_index_collection(window_start, selected_date, geometry)
        if collection.size().getInfo() == 0:
            raise ValueError(f"No cloud-filtered Sentinel-2 observation is available in the 30-day window ending {start}.")
        image = collection.mean().select(band).clip(geometry)
        visualization = {"min": -1, "max": 1, "palette": palettes}
        source = f"Cloud-filtered {S2_DATASET} derived {band}; 30-day regional composite ending {start}"
        unit = "index"
    elif layer in {"s1_vv", "s1_vh"}:
        band = "VV" if layer == "s1_vv" else "VH"
        window_start = selected_date - timedelta(days=30)
        collection = sentinel1_collection(window_start, selected_date, geometry)
        if collection.size().getInfo() == 0:
            raise ValueError(f"No Sentinel-1 observation is available in the 30-day window ending {start}.")
        image = (
            collection.mean().select(band).clip(geometry)
        )
        visualization = {"min": -25, "max": 0, "palette": palettes}
        source = f"Sentinel-1 {S1_DATASET} {band} microwave backscatter; 30-day composite ending {start}; not direct soil moisture"
        unit = "dB"
    else:
        raise ValueError(f"No validated raster layer is available for {layer}.")
    map_info = image.getMapId(visualization)
    return {
        "tile_url": map_info["tile_fetcher"].url_format,
        "source": source,
        "unit": unit,
        "visualization": visualization,
        "observation_date": start,
        "data_mode": "REAL",
    }


def get_latest_smap_observation() -> dict[str, Any]:
    """Return the latest SMAP L4 surface-soil-moisture observation available in Earth Engine.

    SMAP is a near-real-time satellite/model product, not an instantaneous field sensor.
    The function searches a recent window and returns the newest available image.
    Successful results are cached for 15 minutes to match the live dashboard refresh.
    """
    global _latest_smap_cache
    with _latest_smap_cache_lock:
        now = monotonic()
        if (
            _latest_smap_cache is not None
            and now - _latest_smap_cache[0] < LATEST_SMAP_CACHE_TTL_SECONDS
        ):
            return dict(_latest_smap_cache[1])

        observation = _fetch_latest_smap_observation()
        _latest_smap_cache = (monotonic(), observation)
        return dict(observation)


def _fetch_latest_smap_observation() -> dict[str, Any]:
    ee = _earth_engine()
    geometry = _mehsana_geometry(ee)
    today = date.today()
    start = today - timedelta(days=7)
    collection = (
        ee.ImageCollection(SMAP_DATASET)
        .filterBounds(geometry)
        .filterDate(start.isoformat(), (today + timedelta(days=1)).isoformat())
        .select("sm_surface")
        .sort("system:time_start", False)
    )
    if collection.size().getInfo() == 0:
        raise RuntimeError("No SMAP observations were returned for the recent 7-day window.")
    image = ee.Image(collection.first())
    stats = image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geometry,
        scale=11000,
        maxPixels=1_000_000,
        bestEffort=True,
        tileScale=2,
    ).getInfo()
    value = stats.get("sm_surface")
    if value is None or value <= -900:
        raise RuntimeError("Latest SMAP image has no valid soil-moisture value for Mehsana.")
    timestamp = ee.Date(image.get("system:time_start")).format("YYYY-MM-dd'T'HH:mm:ss").getInfo()
    return {
        "timestamp": timestamp,
        "date": timestamp[:10],
        "latitude": 23.59,
        "longitude": 72.37,
        "soil_moisture": value,
        "unit": "m³/m³",
        "source": f"NASA SMAP L4 via Google Earth Engine ({SMAP_DATASET})",
        "data_mode": "REAL",
        "note": "Latest available coarse regional observation; satellite data may have acquisition/processing latency.",
    }
