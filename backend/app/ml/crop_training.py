from __future__ import annotations

import random
from collections import Counter
from datetime import date, timedelta
from math import isfinite
from threading import Lock
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, cohen_kappa_score, confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from app.gee.service import S2_DATASET, _earth_engine, _mehsana_geometry

CROP_SPECTRAL_BANDS = ("B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12")
CROP_INDEX_BANDS = ("NDVI", "NDMI")
CROP_FEATURE_BANDS = (*CROP_SPECTRAL_BANDS, *CROP_INDEX_BANDS)
CROP_DATASETS = {
    "Fennel": "Mahesana_Fennel_Field_Features_2025_2026.csv",
    "Cotton": "Mahesana_cotton_Field_Features_2025_2026.csv",
}
TRAINING_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "training"
CROP_PALETTE = (
    "#2e7d32", "#e6a700", "#8e5b35", "#26a69a", "#ef6c4d",
    "#7e57c2", "#42a5f5", "#c0ca33", "#ec407a", "#78909c",
    "#3949ab", "#9ccc65", "#ff7043", "#26c6da", "#ab47bc",
    "#8d6e63", "#66bb6a", "#ffa726", "#5c6bc0", "#d4e157",
)
MAX_LABEL_FEATURES = 2_000
MAX_CROP_CLASSES = len(CROP_PALETTE)
MAX_PIXELS_PER_CLASS = 1_000

_model_lock = Lock()
_dataset_training_lock = Lock()
_trained_model: dict[str, Any] | None = None
_dataset_model: dict[str, Any] | None = None


def _valid_positions(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    if len(value) >= 2 and all(
        isinstance(coordinate, (int, float)) and not isinstance(coordinate, bool)
        for coordinate in value[:2]
    ):
        longitude, latitude = value[:2]
        return (
            isfinite(longitude)
            and isfinite(latitude)
            and -180 <= longitude <= 180
            and -90 <= latitude <= 90
        )
    return all(_valid_positions(item) for item in value)


def validate_crop_labels(payload: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("Upload a GeoJSON FeatureCollection.")
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("The GeoJSON FeatureCollection must contain labeled polygon features.")
    if len(features) > MAX_LABEL_FEATURES:
        raise ValueError(f"GeoJSON is limited to {MAX_LABEL_FEATURES} polygon features.")
    crs = payload.get("crs")
    if crs and "4326" not in str(crs):
        raise ValueError("Crop-label GeoJSON must use WGS84 longitude/latitude coordinates (EPSG:4326).")

    labels: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"Feature {index + 1} is not a valid GeoJSON Feature.")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"Feature {index + 1} must have a Polygon or MultiPolygon geometry.")
        if not _valid_positions(geometry.get("coordinates")):
            raise ValueError(f"Feature {index + 1} has invalid WGS84 polygon coordinates.")
        crop_type = (feature.get("properties") or {}).get("crop_type")
        if not isinstance(crop_type, str) or not crop_type.strip():
            raise ValueError(f"Feature {index + 1} must have a non-empty crop_type property.")
        crop_type = crop_type.strip()
        if len(crop_type) > 80:
            raise ValueError(f"Feature {index + 1} crop_type must not exceed 80 characters.")
        labels.append({"geometry": geometry, "crop_type": crop_type})
        counts[crop_type] += 1

    if len(counts) < 2:
        raise ValueError("At least two crop_type classes are required for crop classification.")
    if len(counts) > MAX_CROP_CLASSES:
        raise ValueError(f"At most {MAX_CROP_CLASSES} crop classes are supported.")
    underrepresented = sorted(crop for crop, count in counts.items() if count < 3)
    if underrepresented:
        names = ", ".join(underrepresented)
        raise ValueError(f"Each crop class needs at least 3 labeled polygons for a polygon-held-out evaluation: {names}.")
    return labels, sorted(counts)


def crop_model_status() -> dict[str, Any]:
    with _model_lock:
        model = _dataset_model or _trained_model
        if model is None:
            dataset = load_bundled_crop_dataset()
            counts = dataset["frame"]["crop_type"].value_counts().to_dict()
            return {
                "model_available": False,
                "dataset_available": True,
                "dataset_rows": len(dataset["frame"]),
                "datasets": list(CROP_DATASETS.values()),
                "class_counts": counts,
                "date_start": dataset["frame"]["date"].min().date().isoformat(),
                "date_end": dataset["frame"]["date"].max().date().isoformat(),
                "classes": [],
                "feature_bands": list(CROP_SPECTRAL_BANDS),
                "derived_indices": list(CROP_INDEX_BANDS),
                "message": "Bundled Fennel and cotton field-feature datasets are ready. Train to evaluate them and prepare a district crop-classification layer.",
            }
        return {
            "model_available": True,
            "dataset_available": model.get("dataset_available", False),
            "dataset_rows": model.get("dataset_rows"),
            "datasets": list(CROP_DATASETS.values()) if model.get("dataset_available") else [],
            "class_counts": model.get("class_counts", {}),
            "classes": model["classes"],
            "feature_bands": list(CROP_SPECTRAL_BANDS),
            "derived_indices": list(CROP_INDEX_BANDS),
            "date_start": model["date_start"],
            "date_end": model["date_end"],
            "validation": model["validation"],
            "source": model["source"],
            "note": model["note"],
        }


def load_bundled_crop_dataset() -> dict[str, Any]:
    required = {"Field_ID", "Field_Name", "Crop", "Date", *CROP_FEATURE_BANDS}
    frames: list[pd.DataFrame] = []
    for expected_crop, filename in CROP_DATASETS.items():
        path = TRAINING_DATA_DIR / filename
        if not path.is_file():
            raise RuntimeError(f"Bundled crop training dataset is missing: {filename}")
        try:
            frame = pd.read_csv(path)
        except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
            raise RuntimeError(f"Could not read bundled crop training dataset: {filename}") from exc
        missing = required - set(frame.columns)
        if missing:
            raise RuntimeError(f"{filename} is missing required columns: {', '.join(sorted(missing))}.")
        if frame.empty:
            raise RuntimeError(f"Bundled crop training dataset is empty: {filename}")
        if frame["Crop"].isna().any() or not frame["Crop"].astype(str).str.strip().str.casefold().eq(expected_crop.casefold()).all():
            raise RuntimeError(f"{filename} must contain only the expected {expected_crop} Crop label.")
        if frame["Field_ID"].isna().any() or frame["Field_ID"].astype(str).str.strip().eq("").any():
            raise RuntimeError(f"{filename} contains an empty Field_ID.")
        if frame["Field_ID"].duplicated().any():
            raise RuntimeError(f"{filename} contains duplicate Field_ID values.")
        for column in CROP_FEATURE_BANDS:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        features = frame.loc[:, CROP_FEATURE_BANDS].to_numpy(dtype=float)
        if not np.isfinite(features).all():
            raise RuntimeError(f"{filename} has missing or non-finite spectral feature values.")
        if ((frame.loc[:, CROP_SPECTRAL_BANDS] < 0) | (frame.loc[:, CROP_SPECTRAL_BANDS] > 1.5)).any().any():
            raise RuntimeError(f"{filename} has Sentinel-2 reflectance values outside the expected 0–1.5 range.")
        if ((frame.loc[:, CROP_INDEX_BANDS] < -1) | (frame.loc[:, CROP_INDEX_BANDS] > 1)).any().any():
            raise RuntimeError(f"{filename} has vegetation-index values outside the valid −1 to 1 range.")
        parsed_dates = pd.to_datetime(frame["Date"], errors="coerce")
        if parsed_dates.isna().any():
            raise RuntimeError(f"{filename} contains invalid Date values.")
        frame = frame.assign(crop_type=expected_crop, date=parsed_dates)
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True)
    if combined["crop_type"].nunique() < 2:
        raise RuntimeError("Crop training requires at least two classes.")
    return {"frame": combined, "classes": list(CROP_DATASETS)}


def _local_crop_classifier() -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=300,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=42,
        n_jobs=1,
    )


def _evaluate_crop_dataset(frame: pd.DataFrame, class_names: list[str]) -> dict[str, Any]:
    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    features = frame.loc[:, CROP_FEATURE_BANDS]
    labels = frame["crop_type"]
    predictions = cross_val_predict(_local_crop_classifier(), features, labels, cv=folds)
    ordered_names = sorted(class_names)
    matrix = confusion_matrix(labels, predictions, labels=ordered_names)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predictions, labels=ordered_names, zero_division=0
    )
    return {
        "method": "5-fold stratified cross-validation (random record splits)",
        "accuracy": float(accuracy_score(labels, predictions)),
        "kappa": float(cohen_kappa_score(labels, predictions, labels=ordered_names)),
        "baseline_accuracy": float(labels.value_counts(normalize=True).max()),
        "confusion_matrix": matrix.tolist(),
        "class_order": ordered_names,
        "per_class": [
            {
                "crop_type": crop,
                "precision": float(precision[index]),
                "recall": float(recall[index]),
                "f1": float(f1[index]),
                "support": int(matrix[index].sum()),
            }
            for index, crop in enumerate(ordered_names)
        ],
    }


def train_bundled_crop_classifier() -> dict[str, Any]:
    global _dataset_model
    with _dataset_training_lock:
        dataset = load_bundled_crop_dataset()
        frame = dataset["frame"]
        crop_names = dataset["classes"]
        validation = _evaluate_crop_dataset(frame, crop_names)
        local_model = _local_crop_classifier().fit(frame.loc[:, CROP_FEATURE_BANDS], frame["crop_type"])

        ee = _earth_engine()
        class_codes = {crop: index for index, crop in enumerate(sorted(crop_names))}
        examples = [
            ee.Feature(
                None,
                {
                    **{band: float(row[band]) for band in CROP_FEATURE_BANDS},
                    "crop_code": class_codes[row["crop_type"]],
                },
            )
            for row in frame[["crop_type", *CROP_FEATURE_BANDS]].to_dict(orient="records")
        ]
        training_features = ee.FeatureCollection(examples)
        classifier = ee.Classifier.smileRandomForest(
            numberOfTrees=300,
            minLeafPopulation=2,
            seed=42,
        ).train(
            features=training_features,
            classProperty="crop_code",
            inputProperties=list(CROP_FEATURE_BANDS),
        )

        counts = frame["crop_type"].value_counts().to_dict()
        classes = [
            {
                "crop_type": crop,
                "code": class_codes[crop],
                "color": CROP_PALETTE[class_codes[crop]],
                "training_records": int(counts[crop]),
            }
            for crop in sorted(crop_names)
        ]
        trained = {
            "classifier": classifier,
            "local_model": local_model,
            "classes": classes,
            "class_counts": {crop: int(counts[crop]) for crop in sorted(counts)},
            "dataset_rows": len(frame),
            "dataset_available": True,
            "validation": validation,
            "date_start": frame["date"].min().date().isoformat(),
            "date_end": frame["date"].max().date().isoformat(),
            "source": "Bundled Mehsana Fennel and cotton field-feature CSVs; Sentinel-2 spectral bands and NDVI/NDMI",
            "note": "Small spectral-only dataset with no field geometry. Results are experimental; five-fold record-split metrics are near the majority-class baseline and are not independent spatial validation.",
        }
        with _model_lock:
            _dataset_model = trained
        return crop_model_status()


def train_crop_classifier(payload: Any, start_date: Any, end_date: Any) -> dict[str, Any]:
    global _trained_model
    labels, crop_names = validate_crop_labels(payload)
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date.")
    if (end_date - start_date).days < 30:
        raise ValueError("Select a Sentinel-2 training window of at least 30 days.")
    if (end_date - start_date).days > 365:
        raise ValueError("Crop-classifier training windows are limited to 366 days.")

    ee = _earth_engine()
    study_area = _mehsana_geometry(ee)
    counts = Counter(label["crop_type"] for label in labels)
    class_codes = {crop: index for index, crop in enumerate(crop_names)}
    grouped: dict[str, list[dict[str, Any]]] = {crop: [] for crop in crop_names}
    for label in labels:
        grouped[label["crop_type"]].append(label)

    training_features: list[dict[str, Any]] = []
    validation_features: list[dict[str, Any]] = []
    rng = random.Random(42)
    for crop in crop_names:
        polygons = grouped[crop][:]
        rng.shuffle(polygons)
        for polygon_index, label in enumerate(polygons):
            properties = {
                "crop_type": crop,
                "crop_code": class_codes[crop],
                "split": "validation" if polygon_index == len(polygons) - 1 else "train",
            }
            feature = {"type": "Feature", "geometry": label["geometry"], "properties": properties}
            (validation_features if properties["split"] == "validation" else training_features).append(feature)

    labeled_polygons = ee.FeatureCollection(training_features + validation_features)
    reflectance = ee.ImageCollection(S2_DATASET).filterBounds(study_area).filterDate(
        start_date.isoformat(), (end_date + timedelta(days=1)).isoformat()
    ).filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
    if reflectance.size().getInfo() == 0:
        raise ValueError("No cloud-filtered Sentinel-2 scenes are available in the selected training window.")

    def cloud_mask(image):
        qa60 = image.select("QA60")
        mask = qa60.bitwiseAnd(1 << 10).eq(0).And(qa60.bitwiseAnd(1 << 11).eq(0))
        return image.updateMask(mask).select(list(CROP_SPECTRAL_BANDS)).multiply(0.0001)

    composite = reflectance.map(cloud_mask).median()
    composite = composite.addBands([
        composite.normalizedDifference(["B8", "B4"]).rename("NDVI"),
        composite.normalizedDifference(["B8", "B11"]).rename("NDMI"),
    ]).select(list(CROP_FEATURE_BANDS)).clip(study_area)
    label_collection = ee.FeatureCollection(labeled_polygons)

    def sample_class(crop_type: str, split: str):
        code = class_codes[crop_type]
        polygons = label_collection.filter(ee.Filter.eq("crop_code", code)).filter(ee.Filter.eq("split", split))
        region = polygons.geometry()
        return composite.sample(
            region=region,
            scale=20,
            numPixels=MAX_PIXELS_PER_CLASS,
            seed=42 + code,
            dropNulls=True,
            tileScale=4,
            geometries=False,
        ).map(lambda sample: ee.Feature(sample).set("crop_code", code))

    training_samples = None
    validation_samples = None
    for crop in crop_names:
        training = sample_class(crop, "train")
        validation = sample_class(crop, "validation")
        training_samples = training if training_samples is None else training_samples.merge(training)
        validation_samples = validation if validation_samples is None else validation_samples.merge(validation)
    if training_samples is None or validation_samples is None:
        raise RuntimeError("Could not construct crop-classifier training samples.")

    def validate_sample_counts(samples, split: str) -> None:
        histogram = samples.aggregate_histogram("crop_code").getInfo() or {}
        missing = [
            crop for crop, code in class_codes.items()
            if int(histogram.get(str(code), histogram.get(code, 0))) == 0
        ]
        if missing:
            raise ValueError(
                f"Sentinel-2 yielded no valid {split} pixels for: {', '.join(missing)}. "
                "Check polygon overlap, cloud-free imagery, and selected dates."
            )

    validate_sample_counts(training_samples, "training")
    validate_sample_counts(validation_samples, "validation")
    classifier = ee.Classifier.smileRandomForest(numberOfTrees=100, seed=42).train(
        features=training_samples,
        classProperty="crop_code",
        inputProperties=list(CROP_FEATURE_BANDS),
    )
    evaluated = validation_samples.classify(classifier)
    matrix = evaluated.errorMatrix("crop_code", "classification", list(range(len(crop_names))))
    matrix_values = matrix.array().getInfo()
    accuracy = matrix.accuracy().getInfo()
    kappa = matrix.kappa().getInfo()
    if accuracy is None or not matrix_values:
        raise RuntimeError("Sentinel-2 crop-classifier evaluation did not return valid metrics.")

    classes = [
        {"crop_type": crop, "code": class_codes[crop], "color": CROP_PALETTE[class_codes[crop]], "labelled_polygons": counts[crop]}
        for crop in crop_names
    ]
    validation = {
        "method": "Deterministic polygon-held-out split (one polygon per crop class)",
        "accuracy": float(accuracy),
        "kappa": float(kappa) if kappa is not None else None,
        "confusion_matrix": matrix_values,
        "class_order": crop_names,
    }
    trained = {
        "classifier": classifier,
        "composite": composite,
        "classes": classes,
        "validation": validation,
        "date_start": start_date.isoformat(),
        "date_end": end_date.isoformat(),
        "source": f"Sentinel-2 {S2_DATASET}; cloud-masked {start_date.isoformat()} to {end_date.isoformat()} composite",
        "note": "Exploratory model evaluated on held-out labeled polygons from this upload; not independently validated for other fields, seasons, or districts.",
    }
    with _model_lock:
        _trained_model = trained
    return crop_model_status()


def crop_classification_map(selected_date: date | None = None) -> dict[str, Any] | None:
    with _model_lock:
        trained = _dataset_model or _trained_model
    if trained is None:
        return None
    if trained.get("dataset_available"):
        if selected_date is None:
            raise ValueError("A date is required to render the Sentinel-2 crop-classification map.")
        ee = _earth_engine()
        geometry = _mehsana_geometry(ee)
        window_start = selected_date - timedelta(days=30)
        collection = (
            ee.ImageCollection(S2_DATASET)
            .filterBounds(geometry)
            .filterDate(window_start.isoformat(), (selected_date + timedelta(days=1)).isoformat())
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60))
        )
        if collection.size().getInfo() == 0:
            raise ValueError(
                f"No cloud-filtered Sentinel-2 scene is available in the 30-day window ending {selected_date.isoformat()}."
            )

        def cloud_mask(image):
            qa60 = image.select("QA60")
            mask = qa60.bitwiseAnd(1 << 10).eq(0).And(qa60.bitwiseAnd(1 << 11).eq(0))
            return image.updateMask(mask).select(list(CROP_SPECTRAL_BANDS)).multiply(0.0001)

        composite = collection.map(cloud_mask).median()
        composite = composite.addBands([
            composite.normalizedDifference(["B8", "B4"]).rename("NDVI"),
            composite.normalizedDifference(["B8", "B11"]).rename("NDMI"),
        ]).select(list(CROP_FEATURE_BANDS)).clip(geometry)
    else:
        composite = trained["composite"]
    classified = composite.classify(trained["classifier"]).rename("crop_code")
    palette = [entry["color"] for entry in trained["classes"]]
    image = classified.visualize(
        min=0,
        max=len(palette) - 1,
        palette=palette,
        forceRgbOutput=True,
    )
    map_info = image.getMapId()
    return {
        "tile_url": map_info["tile_fetcher"].url_format,
        "source": trained["source"],
        "unit": "crop class",
        "observation_date": selected_date.isoformat() if trained.get("dataset_available") and selected_date else trained["date_end"],
        "data_mode": "REAL",
        "classes": trained["classes"],
        "validation": trained["validation"],
        "note": trained["note"],
    }
