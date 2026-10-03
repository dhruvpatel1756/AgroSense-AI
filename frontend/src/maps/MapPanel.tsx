import { useState, useEffect } from 'react'
import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { Layers2, Maximize2, Search } from 'lucide-react'
import type { Observation, StudyArea } from '../types'
import { api } from '../services/api'

type Props = { observations: Observation[]; layer: string; onLayerChange: (layer: string) => void; isDemo: boolean; center: [number, number]; areaName: string; boundary?: StudyArea['boundary']; cropModelVersion: number }

function MapFocus({ position }: { position: [number, number] }) {
  const map = useMap()
  useEffect(() => { map.setView(position, 8) }, [map, position])
  return null
}

const layerLabels: Record<string, string> = {
  soil_moisture: 'Soil moisture · m³/m³',
  crop_type: 'Crop type · trained classifier',
  ndvi: 'NDVI · unitless',
  ndmi: 'NDMI · unitless',
  ndwi: 'NDWI · unitless',
  s1_vv: 'Sentinel-1 VV · dB',
  s1_vh: 'Sentinel-1 VH · dB',
  rainfall_mm: 'Rainfall · mm',
  moisture_stress: 'Moisture stress · category',
  irrigation_advisory: 'Irrigation advisory · category',
}

const cropColors: Record<string, string> = {
  Cotton: '#5b8f62',
  Wheat: '#d8a746',
  Groundnut: '#b47b50',
  Rice: '#4c91a2',
  Maize: '#cf7654',
  Vegetables: '#8872aa',
  Other: '#78847b',
}

export default function MapPanel({ observations, layer, onLayerChange, isDemo, center, areaName, boundary, cropModelVersion }: Props) {
  const [baseLayer, setBaseLayer] = useState<'street' | 'satellite' | 'terrain'>('street')
  const [fullScreen, setFullScreen] = useState(false)
  const [opacity, setOpacity] = useState(0.82)
  const [search, setSearch] = useState('')
  const [tileUrl, setTileUrl] = useState('')
  const [tileSource, setTileSource] = useState('')
  const [tileMessage, setTileMessage] = useState('')
  const [tileRange, setTileRange] = useState('')
  const [tilePalette, setTilePalette] = useState<string[]>([])
  const [tileClasses, setTileClasses] = useState<{ crop_type: string; color: string }[]>([])
  const selectedDate = observations[observations.length - 1]?.date
  const filtered = observations.filter((row) =>
    `${row.crop ?? ''} ${row.growth_stage ?? ''}`.toLowerCase().includes(search.toLowerCase()),
  ).filter((row, index, rows) => rows.findIndex((candidate) => candidate.latitude === row.latitude && candidate.longitude === row.longitude) === index)
  const cropCategories = [...new Set(filtered.map((row) => row.crop).filter((crop): crop is string => Boolean(crop)))]
  const selectedLayerLabel = layer === 'crop_type' && isDemo ? 'Crop type · demo labels' : layerLabels[layer]

  useEffect(() => {
    if (isDemo || (layer !== 'crop_type' && !selectedDate)) {
      setTileUrl('')
      setTileSource('')
      setTileMessage('')
      setTileRange('')
      setTilePalette([])
      setTileClasses([])
      return
    }
    let current = true
    api.mapLayer(layer, selectedDate ?? new Date().toISOString().slice(0, 10)).then((result) => {
      if (!current) return
      setTileUrl(result.available ? result.tile_url ?? '' : '')
      setTileSource(result.source ?? '')
      setTileMessage(result.available ? '' : result.message ?? 'Raster layer unavailable.')
      setTileRange(result.visualization ? `${result.visualization.min}–${result.visualization.max} ${result.unit ?? ''}` : '')
      setTilePalette(result.visualization?.palette ?? [])
      setTileClasses(result.classes ?? [])
    }).catch(() => {
      if (!current) return
      setTileUrl('')
      setTileSource('')
      setTileMessage('Satellite service temporarily unavailable for this map layer.')
      setTileRange('')
      setTilePalette([])
      setTileClasses([])
    })
    return () => { current = false }
  }, [isDemo, layer, selectedDate, cropModelVersion])

  function colorFor(row: Observation) {
    if (layer === 'crop_type') return row.crop ? cropColors[row.crop] ?? cropColors.Other : '#77847d'
    if (layer === 'irrigation_advisory') {
      if (row.irrigation_advisory?.toLowerCase().includes('recommended')) return '#e25447'
      if (row.irrigation_advisory?.toLowerCase().includes('plan')) return '#e5a642'
      return '#4c9f70'
    }
    if (layer === 'moisture_stress') {
      return row.moisture_stress === 'High Stress' ? '#e25447' : row.moisture_stress === 'Moderate Stress' ? '#e5a642' : '#4c9f70'
    }
    const value = row[layer as keyof Observation]
    if (typeof value !== 'number' || value === null) return '#77847d'
    const thresholds = layer === 'soil_moisture' ? [0.16, 0.22, 0.30]
      : layer === 'ndvi' ? [0.25, 0.45, 0.65]
        : layer === 'ndmi' || layer === 'ndwi' ? [-0.2, 0, 0.2]
          : layer === 's1_vv' || layer === 's1_vh' ? [-20, -15, -10] : [2, 8, 18]
    return value < thresholds[0] ? '#d76655' : value < thresholds[1] ? '#e9ac50' : value < thresholds[2] ? '#98bb62' : '#468c68'
  }

  return (
    <section className={`map-card ${fullScreen ? 'fullscreen' : ''}`}>
      <div className="map-heading">
        <div><div className="eyebrow">GEOSPATIAL OVERVIEW</div><h2>{areaName} agricultural landscape</h2></div>
        <div className="map-actions">
          <label className="map-select"><Layers2 size={15} /><select value={layer} onChange={(event) => onLayerChange(event.target.value)} aria-label="Map layer">{Object.entries(layerLabels).map(([key, label]) => <option key={key} value={key}>{key === 'crop_type' && isDemo ? 'Crop type · demo labels' : label}</option>)}</select></label>
          <button className="icon-button" onClick={() => setBaseLayer((current) => current === 'street' ? 'satellite' : current === 'satellite' ? 'terrain' : 'street')} title={`Basemap: ${baseLayer}. Select next basemap`} aria-label={`Basemap ${baseLayer}; select next`}><Layers2 size={17} /></button>
          <button className="icon-button" onClick={() => setFullScreen(!fullScreen)} title={fullScreen ? 'Exit full screen' : 'Expand map'} aria-label={fullScreen ? 'Exit full screen map' : 'Expand map'}><Maximize2 size={17} /></button>
        </div>
      </div>
      <div className="map-search"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={isDemo ? 'Filter demo locations by crop or stage' : 'Filter available locations by crop or stage'} aria-label="Filter map locations" /></div>
      <div className="map-frame">
        <MapContainer center={center} zoom={8} scrollWheelZoom className="leaflet-map">
          <MapFocus position={center} />
          <TileLayer
            attribution={baseLayer === 'satellite' ? 'Tiles &copy; Esri' : baseLayer === 'terrain' ? 'Map data &copy; OpenTopoMap contributors' : '&copy; OpenStreetMap contributors'}
            url={baseLayer === 'satellite' ? 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}' : baseLayer === 'terrain' ? 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png' : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'}
            opacity={1}
          />
          {tileUrl && <TileLayer key={`${layer}-${selectedDate}`} url={tileUrl} opacity={opacity} attribution={tileSource} />}
          {boundary && <GeoJSON data={boundary} style={{ color: '#355b42', weight: 2, fill: false }} />}
          {filtered.filter((row) => isDemo && (layer !== 'crop_type' || row.crop)).map((row, index) => (
            <CircleMarker key={`${row.date}-${row.latitude}-${index}`} center={[row.latitude, row.longitude]} radius={8} pathOptions={{ color: '#fff', weight: 2, fillColor: colorFor(row), fillOpacity: opacity }}>
              <Tooltip direction="top"><strong>{isDemo ? 'Synthetic demo location' : 'Regional statistic at the study-area reference point'}</strong><br />{row.date}{layer === 'crop_type' ? ` · Demo crop label: ${row.crop}` : ` · Soil moisture: ${row.soil_moisture == null ? 'unavailable' : `${row.soil_moisture.toFixed(3)} m³/m³`}`}<br />{isDemo ? 'Illustrative sample; not a surveyed field boundary or crop-classification result.' : 'SMAP is a coarse regional observation, not a field measurement.'}</Tooltip>
            </CircleMarker>
          ))}
        </MapContainer>
        <div className="map-legend">
          <b>{selectedLayerLabel}</b>
          {layer === 'crop_type' ? (
            <div className="crop-legend">{isDemo
              ? cropCategories.map((crop) => <span key={crop}><i style={{ backgroundColor: cropColors[crop] ?? cropColors.Other }} />{crop}</span>)
              : tileClasses.map((crop) => <span key={crop.crop_type}><i style={{ backgroundColor: crop.color }} />{crop.crop_type}</span>)}</div>
          ) : (
            <>
              <div className="legend-gradient" style={tilePalette.length ? { background: `linear-gradient(90deg, ${tilePalette.join(', ')})` } : undefined} />
              <div className="legend-scale"><span>{tileRange || (layer === 'moisture_stress' || layer === 'irrigation_advisory' ? 'Normal / monitor' : layer === 'soil_moisture' ? 'Drier' : layer === 'ndvi' ? 'Lower' : 'Lower / less')}</span><span>{tileRange ? 'Raster range' : layer === 'moisture_stress' || layer === 'irrigation_advisory' ? 'High / recommended' : layer === 'soil_moisture' ? 'Wetter' : layer === 'ndvi' ? 'Higher' : 'Higher / more'}</span></div>
            </>
          )}
          <small>{layer === 'crop_type' ? isDemo ? 'Labeled synthetic demo records only; no crop classifier or field polygons.' : tileSource ? `${tileSource}. ${tileMessage || 'Exploratory classification; field validation is required.'}` : tileMessage || 'Upload labeled crop polygons in Crop Monitoring to train this map layer.' : tileSource || (layer === 'soil_moisture' ? isDemo ? 'Synthetic demo point values; not an SMAP raster.' : 'NASA SMAP regional product; coarse resolution, not field-scale.' : layer === 'ndmi' || layer === 'ndwi' ? 'Index range: −1 to 1; display thresholds are illustrative.' : layer === 's1_vv' || layer === 's1_vh' ? 'Backscatter in dB · not direct soil moisture.' : layer === 'moisture_stress' || layer === 'irrigation_advisory' ? 'Demo categories only; no validated stress model.' : 'Indicative display scale · thresholds need local calibration.')}</small>
        </div>
        <label className="opacity-control">Layer opacity <input type="range" min="0.2" max="1" step="0.05" value={opacity} onChange={(event) => setOpacity(Number(event.target.value))} /></label>
      </div>
      <div className="map-footer"><span><i className="status-dot" /> {tileUrl ? `${tileSource} · ${layer === 'crop_type' ? 'trained crop classes' : selectedDate}` : layer === 'crop_type' && !isDemo ? 'No real crop classification available' : `${filtered.length} ${isDemo ? 'labeled demo location' : 'regional reference-point marker'}`}</span><span>{tileMessage || 'District boundary: DataMeet · Census 2011 (CC BY 2.5 India) · Base map © OpenStreetMap'}</span></div>
    </section>
  )
}
