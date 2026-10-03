import type { GeoJsonObject } from 'geojson'

export type Observation = {
  date: string
  latitude: number
  longitude: number
  soil_moisture: number | null
  rainfall_mm: number | null
  temperature_c: number | null
  ndvi: number | null
  ndmi: number | null
  ndwi: number | null
  evi: number | null
  savi: number | null
  s1_vv?: number | null
  s1_vh?: number | null
  et0_mm: number | null
  crop: string | null
  growth_stage: string | null
  moisture_stress: string | null
  irrigation_advisory: string | null
  source: string
  data_mode: 'DEMO' | 'REAL'
}

export type StudyArea = {
  id: string
  name: string
  region: string
  center: [number, number]
  boundary?: GeoJsonObject
}

export type ApiResponse<T> = {
  data_mode: 'DEMO' | 'REAL'
  source: string
  observations: T[]
}
