CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS study_areas (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    boundary GEOMETRY(MultiPolygon, 4326),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS study_areas_boundary_gix ON study_areas USING GIST (boundary);

CREATE TABLE IF NOT EXISTS fields (
    id BIGSERIAL PRIMARY KEY,
    study_area_id BIGINT NOT NULL REFERENCES study_areas(id),
    field_code TEXT NOT NULL,
    crop TEXT,
    geometry GEOMETRY(Polygon, 4326) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (study_area_id, field_code)
);
CREATE INDEX IF NOT EXISTS fields_geometry_gix ON fields USING GIST (geometry);

CREATE TABLE IF NOT EXISTS satellite_observations (
    id BIGSERIAL PRIMARY KEY,
    study_area_id BIGINT NOT NULL REFERENCES study_areas(id),
    field_id BIGINT REFERENCES fields(id),
    observed_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    sensor TEXT NOT NULL,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    footprint GEOMETRY(Geometry, 4326),
    properties JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS satellite_observations_area_date_idx ON satellite_observations (study_area_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS satellite_observations_footprint_gix ON satellite_observations USING GIST (footprint);

CREATE TABLE IF NOT EXISTS soil_moisture (
    satellite_observation_id BIGINT PRIMARY KEY REFERENCES satellite_observations(id) ON DELETE CASCADE,
    surface_m3_m3 DOUBLE PRECISION,
    root_zone_m3_m3 DOUBLE PRECISION,
    spatial_resolution_m INTEGER,
    method TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weather_observations (
    id BIGSERIAL PRIMARY KEY,
    study_area_id BIGINT NOT NULL REFERENCES study_areas(id),
    observed_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    temperature_c DOUBLE PRECISION,
    humidity_pct DOUBLE PRECISION,
    wind_kmh DOUBLE PRECISION,
    rainfall_mm DOUBLE PRECISION,
    et0_mm DOUBLE PRECISION,
    is_forecast BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (study_area_id, observed_at, source)
);
CREATE INDEX IF NOT EXISTS weather_observations_area_date_idx ON weather_observations (study_area_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS vegetation_indices (
    satellite_observation_id BIGINT PRIMARY KEY REFERENCES satellite_observations(id) ON DELETE CASCADE,
    ndvi DOUBLE PRECISION,
    ndmi DOUBLE PRECISION,
    ndwi DOUBLE PRECISION,
    evi DOUBLE PRECISION,
    savi DOUBLE PRECISION,
    cloud_fraction DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS crop_classification (
    id BIGSERIAL PRIMARY KEY,
    field_id BIGINT NOT NULL REFERENCES fields(id),
    observed_at TIMESTAMPTZ NOT NULL,
    crop_type TEXT,
    confidence DOUBLE PRECISION,
    model_version TEXT,
    is_validated BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS growth_stages (
    id BIGSERIAL PRIMARY KEY,
    field_id BIGINT NOT NULL REFERENCES fields(id),
    observed_at TIMESTAMPTZ NOT NULL,
    stage TEXT,
    confidence DOUBLE PRECISION,
    model_version TEXT,
    is_validated BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS moisture_stress (
    id BIGSERIAL PRIMARY KEY,
    field_id BIGINT NOT NULL REFERENCES fields(id),
    observed_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    score DOUBLE PRECISION,
    confidence DOUBLE PRECISION,
    model_version TEXT,
    is_validated BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS irrigation_advisories (
    id BIGSERIAL PRIMARY KEY,
    field_id BIGINT REFERENCES fields(id),
    study_area_id BIGINT NOT NULL REFERENCES study_areas(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    confidence DOUBLE PRECISION,
    data_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    disclaimer TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS irrigation_advisories_area_date_idx ON irrigation_advisories (study_area_id, created_at DESC);

CREATE TABLE IF NOT EXISTS model_predictions (
    id BIGSERIAL PRIMARY KEY,
    study_area_id BIGINT NOT NULL REFERENCES study_areas(id),
    field_id BIGINT REFERENCES fields(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    target TEXT NOT NULL,
    prediction JSONB NOT NULL,
    confidence DOUBLE PRECISION,
    model_name TEXT NOT NULL,
    model_version TEXT,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE
);
