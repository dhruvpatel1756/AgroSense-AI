from __future__ import annotations

from app.ml.model_loader import load_model


def classify_stress(features: dict[str, float]) -> dict[str, object]:
    model, metadata = load_model("moisture_stress")
    if model is None or metadata is None:
        return {"status": None, "score": None, "confidence": None, "model_available": False, "message": "Moisture-stress model not available."}
    columns = metadata.get("feature_columns", [])
    missing = set(columns) - features.keys()
    if missing:
        raise ValueError(f"Required stress-model features missing: {sorted(missing)}")
    values = [[features[column] for column in columns]]
    status = str(model.predict(values)[0])
    confidence = float(model.predict_proba(values)[0].max()) if hasattr(model, "predict_proba") else None
    return {"status": status, "score": None, "confidence": confidence, "model_available": True}
