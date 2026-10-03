from __future__ import annotations

import json
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[3]
VALID_MODES = {"DEMO", "REAL"}


def mode() -> str:
    configured = os.getenv("DATA_MODE", "REAL").strip().upper()
    if configured not in VALID_MODES:
        raise RuntimeError("DATA_MODE must be either DEMO or REAL.")
    return configured


def get_study_areas() -> list[dict[str, Any]]:
    boundary_path = ROOT / "data" / "geojson" / "mehsana_district.geojson"
    try:
        with boundary_path.open(encoding="utf-8") as boundary_file:
            boundary = json.load(boundary_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Mehsana district boundary data is missing or invalid.") from exc
    return [{
        "id": "mehsana",
        "name": "Mehsana",
        "region": "Gujarat, India",
        "center": [23.59, 72.37],
        "boundary": boundary,
        "boundary_available": True,
        "boundary_source": "DataMeet India Districts, Census 2011 (CC BY 2.5 India)",
    }]


@lru_cache(maxsize=1)
def _demo_frame() -> pd.DataFrame:
    moisture_path = ROOT / "data" / "sample" / "demo_soil_moisture.csv"
    weather_path = ROOT / "data" / "sample" / "demo_weather.csv"
    if not moisture_path.exists() or not weather_path.exists():
        raise RuntimeError("Demo sample files are missing.")
    moisture = pd.read_csv(moisture_path, parse_dates=["date"])
    weather = pd.read_csv(weather_path, parse_dates=["date"])
    if moisture["date"].duplicated().any() or weather["date"].duplicated().any():
        raise RuntimeError("Demo sample observation dates must be unique before joining.")
    frame = moisture.merge(weather, on="date", how="left", validate="one_to_one")
    required = {"date", "soil_moisture", "rainfall_mm", "latitude", "longitude"}
    if not required.issubset(frame.columns):
        raise RuntimeError("Demo sample file is missing required observation columns.")
    return frame.sort_values("date").reset_index(drop=True)


def get_observations(
    start_date: date | None = None,
    end_date: date | None = None,
    study_area_id: str = "mehsana",
) -> list[dict[str, Any]]:
    if study_area_id != "mehsana":
        return []
    if mode() == "REAL":
        from app.gee.service import get_real_observations

        try:
            return get_real_observations(start_date, end_date)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError("Satellite service temporarily unavailable.") from exc
    frame = _demo_frame()
    if start_date is not None:
        frame = frame[frame["date"].dt.date >= start_date]
    if end_date is not None:
        frame = frame[frame["date"].dt.date <= end_date]
    return [
        {
            **{key: (None if pd.isna(value) else value) for key, value in row.items() if key != "date"},
            "date": row["date"].date().isoformat(),
            "data_mode": "DEMO",
            "source": "Synthetic project demonstration dataset; not a real observation",
        }
        for row in frame.to_dict(orient="records")
    ]


@lru_cache(maxsize=128)
def get_weather(
    start_date: date | None,
    end_date: date | None,
    study_area_id: str,
    forecast_days: int = 0,
) -> list[dict[str, Any]]:
    if study_area_id != "mehsana":
        raise RuntimeError("Weather unavailable for the selected study area.")
    today = date.today()
    if forecast_days:
        params = {
            "latitude": 23.59,
            "longitude": 72.37,
            "timezone": "Asia/Kolkata",
            "forecast_days": forecast_days,
            "daily": "temperature_2m_mean,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,et0_fao_evapotranspiration",
        }
        url = "https://api.open-meteo.com/v1/forecast"
    else:
        end = min(end_date or today, today)
        start = start_date or end.replace(day=1)
        if start > end:
            return []
        params = {
            "latitude": 23.59,
            "longitude": 72.37,
            "timezone": "Asia/Kolkata",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_mean,precipitation_sum,wind_speed_10m_max,et0_fao_evapotranspiration",
        }
        url = "https://archive-api.open-meteo.com/v1/archive"
    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        daily = response.json().get("daily", {})
        dates = daily.get("time", [])
        return [
            {
                "date": day,
                "temperature_c": daily.get("temperature_2m_mean", [None] * len(dates))[index],
                "rainfall_mm": daily.get("precipitation_sum", [None] * len(dates))[index],
                "rain_probability": daily.get("precipitation_probability_max", [None] * len(dates))[index],
                "wind_kmh": daily.get("wind_speed_10m_max", [None] * len(dates))[index],
                "humidity_pct": daily.get("relative_humidity_2m_mean", [None] * len(dates))[index],
                "et0_mm": daily.get("et0_fao_evapotranspiration", [None] * len(dates))[index],
                "forecast": forecast_days > 0,
                "data_mode": "REAL",
                "source": "Open-Meteo forecast" if forecast_days else "Open-Meteo archive API",
            }
            for index, day in enumerate(dates)
        ]
    except (requests.RequestException, ValueError, IndexError) as exc:
        raise RuntimeError("Open-Meteo request failed or returned incomplete daily values.") from exc


def summarize_records(records: list[dict[str, Any]]) -> dict[str, float | int]:
    def mean(field: str) -> float | None:
        values = [row[field] for row in records if isinstance(row.get(field), (int, float))]
        return sum(values) / len(values) if values else None

    return {
        "count": len(records),
        "mean_rainfall_mm": mean("rainfall_mm"),
        "mean_soil_moisture": mean("soil_moisture"),
    }


def get_current_weather(study_area_id: str = "mehsana") -> dict[str, Any]:
    """Fetch current weather conditions from Open-Meteo for the study area."""
    if study_area_id != "mehsana":
        raise RuntimeError("Weather unavailable for the selected study area.")
    params = {
        "latitude": 23.59,
        "longitude": 72.37,
        "timezone": "Asia/Kolkata",
        "current": ",".join([
            "temperature_2m", "relative_humidity_2m", "apparent_temperature",
            "precipitation", "rain", "showers", "cloud_cover",
            "wind_speed_10m", "wind_direction_10m", "et0_fao_evapotranspiration",
        ]),
        "daily": "precipitation_sum,temperature_2m_mean,et0_fao_evapotranspiration",
        "forecast_days": 1,
    }
    try:
        response = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()
        current = payload.get("current", {})
        daily = payload.get("daily", {})
        return {
            "timestamp": current.get("time"),
            "temperature_c": current.get("temperature_2m"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "apparent_temperature_c": current.get("apparent_temperature"),
            "precipitation_mm": current.get("precipitation"),
            "rain_mm": current.get("rain"),
            "showers_mm": current.get("showers"),
            "cloud_cover_pct": current.get("cloud_cover"),
            "wind_kmh": current.get("wind_speed_10m"),
            "wind_direction_deg": current.get("wind_direction_10m"),
            "et0_mm": current.get("et0_fao_evapotranspiration"),
            "today_rainfall_mm": (daily.get("precipitation_sum") or [None])[0],
            "today_temperature_c": (daily.get("temperature_2m_mean") or [None])[0],
            "today_et0_mm": (daily.get("et0_fao_evapotranspiration") or [None])[0],
            "source": "Open-Meteo current conditions",
            "data_mode": "REAL",
        }
    except (requests.RequestException, ValueError, IndexError) as exc:
        raise RuntimeError("Open-Meteo current-weather request failed.") from exc
