import type { ApiResponse, Observation, StudyArea } from '../types'

const API_BASE = import.meta.env.VITE_API_URL ?? ''

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}/api${path}`)
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; data_mode: 'DEMO' | 'REAL' }>('/health'),
  live: () => request<LiveResponse>('/live'),
  studyAreas: () => request<{ study_areas: StudyArea[] }>('/study-areas'),
  observations: (query = '') =>
    request<ApiResponse<Observation>>(`/historical${query ? `?${query}` : ''}`),
  vegetation: (query = '') =>
    request<ApiResponse<VegetationObservation>>(`/vegetation${query ? `?${query}` : ''}`),
  weather: (query = '') => request<{ data_mode: 'DEMO' | 'REAL'; source: string; observations: WeatherObservation[] }>(`/weather${query ? `?${query}` : ''}`),
  advisory: (observationDate = '') => request<AdvisoryResponse>(`/irrigation-advisory${observationDate ? `?observation_date=${encodeURIComponent(observationDate)}` : ''}`),
  sentinel1: (query = '') =>
    request<ApiResponse<{ date: string; VV?: number | null; VH?: number | null }>>(`/satellite/sentinel-1${query ? `?${query}` : ''}`),
  mapLayer: (layer: string, observationDate: string) =>
    request<{ available: boolean; model_available?: boolean; tile_url?: string; source?: string; unit?: string; message?: string; visualization?: { min: number; max: number; palette: string[] }; classes?: CropClass[]; validation?: CropValidation; note?: string }>(`/map/layers/${encodeURIComponent(layer)}?observation_date=${encodeURIComponent(observationDate)}`),
  cropModel: () => request<CropModelStatus>('/crops/model'),
  trainBundledCropModel: async () => {
    const response = await fetch(`${API_BASE}/api/crops/train-dataset`, { method: 'POST' })
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as { detail?: string } | null
      throw new Error(payload?.detail || `Crop-model training failed (${response.status})`)
    }
    return response.json() as Promise<CropModelStatus>
  },
  trainCropModel: async (file: File, startDate: string, endDate: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('start_date', startDate)
    form.append('end_date', endDate)
    const response = await fetch(`${API_BASE}/api/crops/train`, { method: 'POST', body: form })
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as { detail?: string } | null
      const detail = payload?.detail
      throw new Error(detail || `Crop-model training failed (${response.status})`)
    }
    return response.json() as Promise<CropModelStatus>
  },
  insights: (question: string, studyAreaId: string, startDate: string, endDate: string) =>
    fetch(`${API_BASE}/api/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, study_area_id: studyAreaId, start_date: startDate, end_date: endDate }),
    }).then(async (response) => {
      if (!response.ok) throw new Error(await response.text())
      return response.json() as Promise<{ answer: string; evidence: string[] }>
    }),
}

export type CropClass = { crop_type: string; code: number; color: string; labelled_polygons: number; training_records?: number }

export type CropValidation = {
  method: string
  accuracy: number
  kappa: number | null
  baseline_accuracy?: number
  confusion_matrix: number[][]
  class_order: string[]
  per_class?: { crop_type: string; precision: number; recall: number; f1: number; support: number }[]
}

export type CropModelStatus = {
  data_mode?: 'DEMO' | 'REAL'
  model_available: boolean
  dataset_available?: boolean
  dataset_rows?: number
  datasets?: string[]
  class_counts?: Record<string, number>
  classes: CropClass[]
  feature_bands: string[]
  derived_indices: string[]
  date_start?: string
  date_end?: string
  validation?: CropValidation
  source?: string
  note?: string
  message?: string
}

export type VegetationObservation = Record<string, string | number | null> & { date: string }

export type AdvisoryResponse = {
  status: string
  reason: string
  confidence: number | null
}

export type WeatherObservation = {
  date: string
  temperature_c: number | null
  rainfall_mm: number | null
  wind_kmh: number | null
  humidity_pct?: number | null
  et0_mm: number | null
  rain_probability?: number | null
  forecast?: boolean
  source: string
  data_mode: 'DEMO' | 'REAL'
}


export type LiveResponse = {
  data_mode: 'DEMO' | 'REAL'
  source: string
  satellite: { timestamp: string; date: string; soil_moisture: number; unit: string; source: string; note?: string } | null
  weather: { timestamp: string; temperature_c: number | null; humidity_pct: number | null; apparent_temperature_c: number | null; precipitation_mm: number | null; rain_mm: number | null; showers_mm: number | null; cloud_cover_pct: number | null; wind_kmh: number | null; wind_direction_deg: number | null; et0_mm: number | null; today_rainfall_mm: number | null; today_temperature_c: number | null; today_et0_mm: number | null; source: string; data_mode: 'REAL' } | null
}
