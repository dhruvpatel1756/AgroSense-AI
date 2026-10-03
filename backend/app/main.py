from __future__ import annotations

import logging
import json
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.services.data_service import (
    get_observations,
    get_study_areas,
    get_weather,
    get_current_weather,
    mode,
    summarize_records,
)
from app.services.advisory import build_advisory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("agrosense.api")

app = FastAPI(
    title="AgroSense AI API",
    description=(
        "Transparent agricultural remote-sensing research prototype. "
        "DEMO records are synthetic examples, not measured observations."
    ),
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    study_area_id: str = "mehsana"
    observation_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None


class AnalyzeResponse(BaseModel):
    answer: str
    evidence: list[str]
    data_mode: str


class AdvisoryRequest(BaseModel):
    soil_moisture: float | None = Field(ge=0, le=1)
    rainfall_mm: float | None = Field(ge=0)
    ndvi: float | None = Field(default=None, ge=-1, le=1)
    ndmi: float | None = Field(default=None, ge=-1, le=1)
    crop: str | None = None
    growth_stage: str | None = None


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "data_mode": mode()}




@app.get("/api/live")
def live_data(study_area_id: str = "mehsana") -> dict[str, Any]:
    """Return the latest available satellite observation plus current weather."""
    if mode() != "REAL":
        return {"data_mode": "DEMO", "source": "Live endpoint requires DATA_MODE=REAL", "satellite": None, "weather": None}
    try:
        from app.gee.service import get_latest_smap_observation
        satellite = get_latest_smap_observation()
        weather = get_current_weather(study_area_id)
        return {"data_mode": "REAL", "source": "Google Earth Engine + Open-Meteo", "satellite": satellite, "weather": weather}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/study-areas")
def study_areas() -> dict[str, Any]:
    return {"study_areas": get_study_areas(), "data_mode": mode()}


@app.get("/api/historical")
def historical(
    start_date: date | None = None,
    end_date: date | None = None,
    study_area_id: str = Query(default="mehsana", min_length=1, max_length=80),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    all_records = get_observations(start_date, end_date, study_area_id)
    records = all_records[offset : offset + limit]
    return {
        "data_mode": mode(),
        "source": "Labeled synthetic project demonstration dataset" if mode() == "DEMO" else "Configured live providers",
        "observations": records,
        "count": len(records),
        "total_count": len(all_records),
        "next_offset": offset + len(records) if offset + len(records) < len(all_records) else None,
    }


@app.get("/api/soil-moisture")
def soil_moisture(
    start_date: date | None = None,
    end_date: date | None = None,
    study_area_id: str = "mehsana",
) -> dict[str, Any]:
    records = get_observations(start_date, end_date, study_area_id)
    available = [row for row in records if row["soil_moisture"] is not None]
    values = [row["soil_moisture"] for row in available]
    return {
        "data_mode": mode(),
        "source": "DEMO sample series" if mode() == "DEMO" else "NASA/SMAP/SPL4SMGP/008",
        "observations": available,
        "statistics": {
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
            "mean": sum(values) / len(values) if values else None,
        },
    }


@app.get("/api/soil-moisture/{observation_date}")
def soil_moisture_by_date(observation_date: date) -> dict[str, Any]:
    rows = get_observations(observation_date, observation_date)
    if not rows:
        raise HTTPException(status_code=404, detail="Data unavailable for selected date.")
    return {"data_mode": mode(), "date": observation_date, "observations": rows}


@app.get("/api/weather")
def weather(
    start_date: date | None = None,
    end_date: date | None = None,
    study_area_id: str = "mehsana",
    forecast_days: int = Query(default=0, ge=0, le=10),
) -> dict[str, Any]:
    if mode() == "REAL":
        try:
            records = get_weather(start_date, end_date, study_area_id, forecast_days)
            return {"data_mode": "REAL", "source": "Open-Meteo", "observations": records}
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=f"Weather service temporarily unavailable: {exc}") from exc
    if forecast_days:
        return {
            "data_mode": "DEMO",
            "source": "No weather forecast is bundled with the demo records.",
            "forecast_available": False,
            "observations": [],
        }
    records = get_observations(start_date, end_date, study_area_id)
    return {"data_mode": "DEMO", "source": "Labeled synthetic project demonstration dataset", "observations": records}


@app.get("/api/rainfall")
def rainfall(start_date: date | None = None, end_date: date | None = None) -> dict[str, Any]:
    records = get_observations(start_date, end_date) if mode() == "DEMO" else get_weather(start_date, end_date, "mehsana")
    return {"data_mode": mode(), "source": "Labeled demo weather rows" if mode() == "DEMO" else "Open-Meteo historical weather", "observations": [{k: row.get(k) for k in ("date", "rainfall_mm", "source", "data_mode")} for row in records]}


@app.get("/api/vegetation")
def vegetation(start_date: date | None = None, end_date: date | None = None) -> dict[str, Any]:
    if mode() == "REAL":
        from app.gee.service import get_sentinel2_indices

        end = end_date or date.today()
        start = start_date or date.fromordinal(end.toordinal() - 30)
        if start > end:
            raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
        try:
            observations = get_sentinel2_indices(start, end)
        except RuntimeError:
            raise
        except Exception as exc:
            logger.exception("Sentinel-2 service request failed")
            raise HTTPException(status_code=503, detail="Satellite service temporarily unavailable.") from exc
        return {"data_mode": "REAL", "source": "Sentinel-2 cloud-filtered regional vegetation indices", "observations": observations}
    records = get_observations(start_date, end_date)
    indices = ("ndvi", "ndmi", "ndwi", "evi", "savi")
    return {"data_mode": mode(), "source": "DEMO indices are illustrative, not derived satellite products" if mode() == "DEMO" else "Sentinel-2 derived index service", "observations": [{**{k: row[k] for k in ("date", *indices)}, "source": row["source"]} for row in records]}


@app.get("/api/ndvi")
def ndvi(start_date: date | None = None, end_date: date | None = None) -> dict[str, Any]:
    return vegetation(start_date, end_date)


@app.get("/api/ndmi")
def ndmi(start_date: date | None = None, end_date: date | None = None) -> dict[str, Any]:
    return vegetation(start_date, end_date)


@app.get("/api/satellite/sentinel-1")
def sentinel1(start_date: date | None = None, end_date: date | None = None) -> dict[str, Any]:
    if mode() == "DEMO":
        return {"data_mode": "DEMO", "source": "Sentinel-1 service not invoked for demo records", "observations": []}
    from app.gee.service import get_sentinel1_observations

    end = end_date or date.today()
    start = start_date or date.fromordinal(end.toordinal() - 30)
    if start > end:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    try:
        observations = get_sentinel1_observations(start, end)
    except RuntimeError:
        raise
    except Exception as exc:
        logger.exception("Sentinel-1 service request failed")
        raise HTTPException(status_code=503, detail="Satellite service temporarily unavailable.") from exc
    return {"data_mode": "REAL", "source": "Sentinel-1 VV/VH microwave backscatter; not direct soil-moisture retrieval", "observations": observations}


@app.get("/api/map/layers/{layer}")
def map_layer(
    layer: str,
    observation_date: date = Query(default_factory=date.today),
) -> dict[str, Any]:
    if layer == "crop_type":
        from app.ml.crop_training import crop_classification_map, crop_model_status

        if mode() == "DEMO":
            return {
                "available": False,
                "data_mode": "DEMO",
                "model_available": False,
                "message": "A real crop-classification raster is not shown in demo mode.",
            }
        try:
            classification = crop_classification_map(observation_date)
        except RuntimeError:
            raise
        except ValueError as exc:
            return {
                "available": False,
                "data_mode": "REAL",
                "model_available": crop_model_status()["model_available"],
                "message": str(exc),
            }
        except Exception as exc:
            logger.exception("Earth Engine crop-classification map request failed")
            raise HTTPException(status_code=503, detail="Crop-classification map temporarily unavailable.") from exc
        if classification is None:
            return {
                "available": False,
                "data_mode": "REAL",
                "model_available": False,
                "message": crop_model_status()["message"],
            }
        return {"available": True, "model_available": True, **classification}
    allowed_layers = {"soil_moisture", "ndvi", "ndmi", "ndwi", "s1_vv", "s1_vh"}
    if layer not in allowed_layers:
        return {
            "available": False,
            "data_mode": mode(),
            "message": "No calibrated raster layer is available for this variable.",
        }
    if mode() == "DEMO":
        return {
            "available": False,
            "data_mode": "DEMO",
            "message": "Raster tiles are unavailable in demo mode; sample values are shown as labeled point markers.",
        }
    from app.gee.service import get_map_layer

    try:
        return {"available": True, **get_map_layer(layer, observation_date)}
    except ValueError as exc:
        return {
            "available": False,
            "data_mode": "REAL",
            "message": str(exc),
        }
    except RuntimeError:
        raise
    except Exception as exc:
        logger.exception("Earth Engine raster request failed")
        raise HTTPException(status_code=503, detail="Satellite service temporarily unavailable for this map layer.") from exc


@app.get("/api/crops")
def crops() -> dict[str, Any]:
    records = get_observations()
    if mode() == "DEMO":
        return {
            "data_mode": "DEMO",
            "source": "Labeled demo examples; crop-classification model unavailable.",
            "model_available": False,
            "observations": [{"date": row["date"], "crop": row["crop"], "confidence": None, "model_available": False} for row in records],
        }
    from app.ml.crop_training import crop_model_status

    model = crop_model_status()
    return {
        "data_mode": "REAL",
        "source": "Sentinel-2 crop-classification model" if model["model_available"] else "Crop-classification model unavailable; SMAP observations do not identify crop type.",
        "model_available": model["model_available"],
        "classes": model["classes"],
        "observations": [],
    }


@app.get("/api/crops/model")
def crop_classifier_status() -> dict[str, Any]:
    from app.ml.crop_training import crop_model_status

    return {"data_mode": mode(), **crop_model_status()}


@app.post("/api/crops/train")
async def train_crop_model(
    file: UploadFile = File(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
) -> dict[str, Any]:
    if mode() != "REAL":
        raise HTTPException(status_code=409, detail="Crop-classifier training requires REAL mode and configured Earth Engine access.")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".geojson", ".json"}:
        raise HTTPException(status_code=415, detail="Upload ground-truth crop polygons as a GeoJSON file.")
    contents = await file.read(10_000_001)
    if len(contents) > 10_000_000:
        raise HTTPException(status_code=413, detail="Crop-label GeoJSON exceeds the 10 MB upload limit.")
    try:
        labels = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Crop-label GeoJSON is invalid JSON.") from exc

    from app.ml.crop_training import train_crop_classifier

    try:
        result = train_crop_classifier(labels, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError:
        raise
    except Exception as exc:
        logger.exception("Crop-classifier training failed")
        raise HTTPException(status_code=503, detail="Crop-classifier training failed in the configured satellite service.") from exc
    return {"data_mode": "REAL", **result}


@app.post("/api/crops/train-dataset")
def train_crop_dataset_model() -> dict[str, Any]:
    if mode() != "REAL":
        raise HTTPException(status_code=409, detail="Crop-classifier training requires REAL mode and configured Earth Engine access.")
    from app.ml.crop_training import train_bundled_crop_classifier

    try:
        result = train_bundled_crop_classifier()
    except RuntimeError:
        raise
    except Exception as exc:
        logger.exception("Bundled crop-dataset training failed")
        raise HTTPException(status_code=503, detail="Crop-dataset training failed in the configured Earth Engine service.") from exc
    return {"data_mode": "REAL", **result}


@app.get("/api/growth-stage")
def growth_stage() -> dict[str, Any]:
    records = get_observations()
    source = "Labeled demo examples; validated temporal growth-stage model unavailable." if mode() == "DEMO" else "Temporal growth-stage model unavailable; no growth-stage prediction is returned."
    return {"data_mode": mode(), "source": source, "observations": [{"date": row["date"], "growth_stage": row["growth_stage"], "confidence": None, "model_available": False} for row in records]}


@app.get("/api/moisture-stress")
def moisture_stress() -> dict[str, Any]:
    records = get_observations()
    source = "Labeled demo rule categories; no validated stress model is configured." if mode() == "DEMO" else "Validated moisture-stress model unavailable; no stress classification is returned."
    return {"data_mode": mode(), "source": source, "observations": [{"date": row["date"], "status": row["moisture_stress"], "score": None, "confidence": None, "model_available": False} for row in records]}


@app.get("/api/irrigation-advisory")
def irrigation_advisory(observation_date: date | None = None) -> dict[str, Any]:
    records = get_observations(observation_date, observation_date)
    latest = records[-1] if records else None
    if latest is None:
        return {"data_mode": mode(), "status": "Data unavailable", "reason": "No observations available for this location/date.", "confidence": None, "recommendation_type": "unavailable"}
    result = build_advisory(latest)
    return {**result, "data_mode": mode(), "observation_date": latest["date"]}


@app.get("/api/fields/{field_id}")
def field_detail(field_id: str) -> dict[str, Any]:
    if mode() != "DEMO":
        raise HTTPException(status_code=503, detail="Field-level data is unavailable until a study area and field dataset are configured.")
    try:
        field_number = int(field_id.removeprefix("demo-field-"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Field not found.") from exc
    records = get_observations()
    if field_number < 1 or field_number > len(records):
        raise HTTPException(status_code=404, detail="Field not found.")
    return {"data_mode": "DEMO", "field_id": f"demo-field-{field_number}", "source": "Synthetic demonstration record; not a surveyed field boundary.", "observation": records[field_number - 1]}


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    if request.start_date and request.end_date and request.start_date > request.end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    records = get_observations(
        request.observation_date or request.start_date,
        request.observation_date or request.end_date,
        request.study_area_id,
    )
    if not records:
        return AnalyzeResponse(answer="I don't have sufficient data for this location/date.", evidence=[], data_mode=mode())
    summary = summarize_records(records)
    question = request.question.casefold()
    if "rain" in question or "precipitation" in question:
        if summary["mean_rainfall_mm"] is None:
            return AnalyzeResponse(answer="I don't have sufficient rainfall data for this location/date.", evidence=[], data_mode=mode())
        answer = f"The available {mode().lower()} records contain a mean daily rainfall of {summary['mean_rainfall_mm']:.1f} mm across {summary['count']} rows."
    elif "moisture" in question or "changed" in question or "week" in question:
        values = [row for row in records if isinstance(row.get("soil_moisture"), (int, float))]
        if len(values) < 2:
            return AnalyzeResponse(answer="I don't have sufficient dated soil-moisture history to compare observations for this location/date.", evidence=[], data_mode=mode())
        change = values[-1]["soil_moisture"] - values[0]["soil_moisture"]
        answer = f"Soil moisture changed by {change:+.3f} m³/m³ from {values[0]['date']} ({values[0]['soil_moisture']:.3f}) to {values[-1]['date']} ({values[-1]['soil_moisture']:.3f}) in the available {mode().lower()} records."
    elif "stress" in question or "area" in question:
        stress_records = [row for row in records if row.get("moisture_stress") is not None]
        if not stress_records:
            return AnalyzeResponse(answer="I don't have sufficient moisture-stress data for this location/date.", evidence=[], data_mode=mode())
        stressed = sum(row["moisture_stress"] in ("Moderate Stress", "High Stress") for row in stress_records)
        answer = f"{stressed} of {len(stress_records)} available {mode().lower()} records are categorized as Watch/Stress in the illustrative demo rules; this is not a validated stress model."
    elif "irrigation" in question or "recommend" in question:
        answer = f"The latest available record's demonstration advisory is “{records[-1]['irrigation_advisory']}”. It is not a field-validated irrigation prescription."
    else:
        answer = f"I can summarize the available {mode().lower()} records, but no trained agricultural language model is configured. These sample data must not be interpreted as real satellite or weather observations."
    return AnalyzeResponse(
        answer=answer,
        evidence=[
            f"Data mode: {mode()}",
            f"Records considered: {summary['count']}",
            "Source: labeled synthetic project demonstration dataset" if mode() == "DEMO" else "Source: configured live service",
        ],
        data_mode=mode(),
    )


@app.post("/api/advisory")
def advisory(payload: AdvisoryRequest) -> dict[str, Any]:
    inputs = payload.model_dump()
    if payload.soil_moisture is None or payload.rainfall_mm is None:
        return {"status": "Field verification recommended", "reason": "Required observations are missing.", "confidence": None, "data_mode": "REAL"}
    return {**build_advisory(inputs), "data_mode": "REAL", "confidence": None}


@app.post("/api/predict")
def predict(payload: dict[str, Any]) -> dict[str, Any]:
    return {"status": "Model unavailable", "prediction": None, "confidence": None, "message": "No validated model artifact and matching evaluation dataset are configured.", "data_mode": mode()}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".geojson", ".json"}:
        raise HTTPException(status_code=415, detail="Upload a CSV, GeoJSON, or JSON file.")
    contents = await file.read(10_000_001)
    if len(contents) > 10_000_000:
        raise HTTPException(status_code=413, detail="File exceeds the 10 MB upload limit.")
    if suffix == ".csv":
        try:
            frame = pd.read_csv(BytesIO(contents), nrows=5000)
        except (ValueError, pd.errors.ParserError) as exc:
            raise HTTPException(status_code=422, detail="Could not parse the uploaded CSV.") from exc
        return {"filename": Path(file.filename or "upload.csv").name, "rows_previewed": len(frame), "columns": list(frame.columns), "persisted": False}
    try:
        payload = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Uploaded JSON is invalid.") from exc
    if suffix == ".geojson" and (
        not isinstance(payload, dict)
        or payload.get("type") != "FeatureCollection"
        or not isinstance(payload.get("features"), list)
    ):
        raise HTTPException(status_code=422, detail="GeoJSON must be a FeatureCollection with a features array.")
    return {"filename": Path(file.filename or "upload.geojson").name, "bytes_received": len(contents), "persisted": False, "message": "GeoJSON parsed and validated; not stored."}


@app.exception_handler(Exception)
async def unhandled_error_handler(_request, exc: Exception):
    logger.exception("Unhandled request error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal service error."})


@app.exception_handler(RuntimeError)
async def unavailable_service_handler(_request, exc: RuntimeError):
    logger.warning("Configured data service unavailable: %s", exc)
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# Production single-service deployment:
# The React build is copied to /app/frontend-dist by the root Dockerfile.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend-dist"
if FRONTEND_DIST.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        base = FRONTEND_DIST.resolve()
        requested = (base / full_path).resolve()
        try:
            inside = requested.is_relative_to(base)
        except AttributeError:
            inside = str(requested).startswith(str(base))
        if full_path and inside and requested.is_file():
            return FileResponse(requested)
        return FileResponse(base / "index.html")
