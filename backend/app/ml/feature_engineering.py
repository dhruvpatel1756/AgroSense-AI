from __future__ import annotations

import numpy as np
import pandas as pd

SENTINEL2_BANDS = ("B2", "B3", "B4", "B8", "B11")
INDEX_FEATURES = ("ndvi", "ndmi", "ndwi", "evi", "savi")


def add_vegetation_indices(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"B2", "B3", "B4", "B8", "B11"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Required Sentinel-2 bands missing: {sorted(required - set(frame.columns))}")
    reflectance = frame.loc[:, SENTINEL2_BANDS].astype(float) * 0.0001
    blue, green, red, nir, swir = (reflectance[band] for band in SENTINEL2_BANDS)

    def ratio(numerator, denominator):
        return numerator / denominator.replace(0, np.nan)

    result = frame.copy()
    result["ndvi"] = ratio(nir - red, nir + red)
    result["ndmi"] = ratio(nir - swir, nir + swir)
    result["ndwi"] = ratio(green - nir, green + nir)
    result["evi"] = 2.5 * ratio(nir - red, nir + 6 * red - 7.5 * blue + 1)
    result["savi"] = 1.5 * ratio(nir - red, nir + red + 0.5)
    return result
