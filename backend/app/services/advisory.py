from __future__ import annotations

import os
from typing import Any


def _thresholds() -> tuple[float, float]:
    try:
        stress = float(os.getenv("IRRIGATION_STRESS_THRESHOLD", "0.16"))
        watch = float(os.getenv("IRRIGATION_WATCH_THRESHOLD", "0.22"))
    except ValueError as exc:
        raise RuntimeError("Irrigation thresholds must be valid numbers between 0 and 1.") from exc
    if not 0 <= stress <= watch <= 1:
        raise RuntimeError("Irrigation thresholds must satisfy 0 <= stress <= watch <= 1.")
    return stress, watch


def build_advisory(observation: dict[str, Any]) -> dict[str, Any]:
    moisture = observation.get("soil_moisture")
    rainfall = observation.get("rainfall_mm")
    if not isinstance(moisture, (int, float)) or not isinstance(rainfall, (int, float)):
        return {
            "status": "Field verification recommended",
            "reason": "Soil-moisture or rainfall observations are unavailable.",
            "confidence": None,
            "recommendation_type": "insufficient_data",
            "observations": {"soil_moisture": moisture, "rainfall_mm": rainfall},
            "disclaimer": "Advisory support only — verify field conditions before irrigation.",
        }
    stress_threshold, watch_threshold = _thresholds()
    if moisture < stress_threshold and rainfall < 5:
        status, reason = "Irrigation recommended", "The illustrative demo moisture value is low and recent demo rainfall is limited."
    elif moisture < watch_threshold:
        status, reason = "Plan irrigation", "The illustrative demo moisture value is below a configurable research threshold; check forecast and field conditions."
    elif rainfall >= 10:
        status, reason = "Continue monitoring", "The illustrative demo record includes recent rainfall; confirm soil and crop response."
    else:
        status, reason = "No irrigation required immediately", "The illustrative demo value is above the configured demonstration threshold."
    return {
        "status": status,
        "reason": reason,
        "confidence": None,
        "recommendation_type": "demo_rule" if observation.get("data_mode") == "DEMO" else "rule_based",
        "observations": {"soil_moisture": moisture, "rainfall_mm": rainfall},
        "data_sources": [observation.get("source", "Application observations")],
        "thresholds": {
            "stress_m3_m3": stress_threshold,
            "watch_m3_m3": watch_threshold,
            "calibration": "Research defaults; not locally validated.",
        },
        "disclaimer": "Advisory support only — verify field conditions before irrigation. Demonstration thresholds are not locally calibrated.",
    }
