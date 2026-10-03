from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import joblib

MODEL_DIR = Path(__file__).resolve().parents[3] / "models"


@lru_cache(maxsize=4)
def load_model(model_name: str):
    if Path(model_name).name != model_name:
        raise ValueError("Model name must not contain a filesystem path.")
    model_path = MODEL_DIR / f"{model_name}.joblib"
    metadata_path = MODEL_DIR / f"{model_name}.metadata.json"
    if not model_path.is_file() or not metadata_path.is_file():
        return None, None
    with metadata_path.open(encoding="utf-8") as metadata_file:
        metadata = json.load(metadata_file)
    return joblib.load(model_path), metadata
