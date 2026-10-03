from __future__ import annotations


def predict_time_series(observations: list[dict[str, object]], horizon_days: int) -> dict[str, object]:
    if not 1 <= horizon_days <= 30:
        raise ValueError("horizon_days must be between 1 and 30.")
    return {
        "predictions": [],
        "confidence": None,
        "model_available": False,
        "message": "Time-series prediction unavailable: no validated forecast model is configured.",
        "input_observations": len(observations),
    }
