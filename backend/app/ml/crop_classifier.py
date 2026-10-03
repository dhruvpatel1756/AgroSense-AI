from __future__ import annotations

from app.ml.model_loader import load_model


def classify_crop(features: dict[str, float]) -> dict[str, object]:
    model, metadata = load_model("crop_classifier")
    if model is None or metadata is None:
        return {"crop": None, "confidence": None, "model_available": False, "message": "Crop classification model not available."}
    columns = metadata.get("feature_columns", [])
    missing = set(columns) - features.keys()
    if missing:
        raise ValueError(f"Required crop-model features missing: {sorted(missing)}")
    prediction = model.predict([[features[column] for column in columns]])[0]
    confidence = None
    if hasattr(model, "predict_proba"):
        confidence = float(model.predict_proba([[features[column] for column in columns]])[0].max())
    return {"crop": str(prediction), "confidence": confidence, "model_available": True}
