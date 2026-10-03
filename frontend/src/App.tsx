import { useEffect, useMemo, useState } from 'react'
import {
  Activity, BarChart3, Bell, ChevronDown, CloudSun, Droplets, FileText, FlaskConical, Gauge,
  Globe2, LayoutDashboard, Leaf, Menu, Radio, Search, Settings, ShieldAlert, Sprout, Waves, X,
} from 'lucide-react'
import Analytics from './charts/Analytics'
import Assistant from './components/Assistant'
import CropTrainingPanel from './components/CropTrainingPanel'
import MapPanel from './maps/MapPanel'
import { api, type AdvisoryResponse, type WeatherObservation, type LiveResponse, type VegetationObservation } from './services/api'
import type { Observation, StudyArea } from './types'

const navigation = [
  { group: 'WORKSPACE', items: [
    ['Dashboard', LayoutDashboard], ['Live Monitoring', Radio], ['Historical Analysis', BarChart3],
  ] },
  { group: 'INSIGHTS', items: [
    ['Soil Moisture', Droplets], ['Weather & Rainfall', CloudSun], ['Crop Monitoring', Sprout],
    ['Vegetation Indices', Leaf], ['Moisture Stress', ShieldAlert], ['Irrigation Advisory', Waves],
  ] },
  { group: 'TOOLS', items: [
    ['Satellite Explorer', Globe2], ['AI Insights', Activity], ['Reports', FileText], ['Settings', Settings],
  ] },
] as const

function getTimeGreeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

function App() {
  const [page, setPage] = useState<string>('Dashboard')
  const [greeting, setGreeting] = useState(getTimeGreeting)
  const [observations, setObservations] = useState<Observation[]>([])
  const [studyAreas, setStudyAreas] = useState<StudyArea[]>([])
  const [studyArea, setStudyArea] = useState('mehsana')
  const [layer, setLayer] = useState('soil_moisture')
  const [range, setRange] = useState('30')
  const [error, setError] = useState('')
  const [dataMode, setDataMode] = useState<'DEMO' | 'REAL' | null>(null)
  const [weatherRows, setWeatherRows] = useState<WeatherObservation[]>([])
  const [satelliteIndexRows, setSatelliteIndexRows] = useState<VegetationObservation[]>([])
  const [live, setLive] = useState<LiveResponse | null>(null)
  const [lastLiveRefresh, setLastLiveRefresh] = useState<string>('')
  const [forecastRows, setForecastRows] = useState<WeatherObservation[]>([])
  const [advisory, setAdvisory] = useState<{ status: string; reason: string; confidence: number | null } | null>(null)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [dateA, setDateA] = useState('')
  const [dateB, setDateB] = useState('')
  const [tableSearch, setTableSearch] = useState('')
  const [tablePage, setTablePage] = useState(0)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [presentation, setPresentation] = useState(false)
  const [cropModelVersion, setCropModelVersion] = useState(0)
  const latest = observations[observations.length - 1]
  const latestSatelliteVegetation = [...satelliteIndexRows].reverse().find((row) => typeof row.NDVI === 'number') ?? null
  const latestDemoVegetation = [...observations].reverse().find((row) => row.ndvi !== null) ?? null
  const latestNdvi = dataMode === 'REAL'
    ? typeof latestSatelliteVegetation?.NDVI === 'number' ? latestSatelliteVegetation.NDVI : null
    : latestDemoVegetation?.ndvi ?? null
  const latestNdviDate = dataMode === 'REAL' ? latestSatelliteVegetation?.date : latestDemoVegetation?.date
  const liveSoilMoisture = live?.satellite?.soil_moisture ?? latest?.soil_moisture ?? null
  const liveTemperature = dataMode === 'REAL' ? live?.weather?.temperature_c ?? null : latest?.temperature_c ?? null
  const liveRainfall = dataMode === 'REAL' ? live?.weather?.today_rainfall_mm ?? null : latest?.rainfall_mm ?? null
  const liveEt0 = dataMode === 'REAL' ? live?.weather?.today_et0_mm ?? null : latest?.et0_mm ?? null
  const activeStudyArea = studyAreas.find((area) => area.id === studyArea)
  const mapCenter: [number, number] = activeStudyArea?.center ?? [23.59, 72.37]
  const dataModeLabel = dataMode ?? 'CONNECTING'
  const rangeStart = new Date()
  rangeStart.setDate(rangeStart.getDate() - Number(range))
  const assistantStart = startDate && endDate ? startDate : rangeStart.toISOString().slice(0, 10)
  const assistantEnd = startDate && endDate ? endDate : new Date().toISOString().slice(0, 10)

  useEffect(() => {
    const timer = window.setInterval(() => setGreeting(getTimeGreeting()), 60_000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    let active = true
    let retryTimer: number | undefined
    const connect = async () => {
      const [areasResult, healthResult] = await Promise.allSettled([api.studyAreas(), api.health()])
      if (!active) return
      if (areasResult.status === 'fulfilled') setStudyAreas(areasResult.value.study_areas)
      if (healthResult.status === 'fulfilled') setDataMode(healthResult.value.data_mode)
      if (areasResult.status === 'rejected' || healthResult.status === 'rejected') {
        setError('API unavailable. Retrying connection; no sample or estimated data is being shown.')
        retryTimer = window.setTimeout(connect, 5000)
      }
    }
    void connect()
    return () => {
      active = false
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
    }
  }, [])
  useEffect(() => {
    let active = true
    const refreshLive = async () => {
      if (dataMode !== 'REAL') return
      try {
        const result = await api.live()
        if (active) { setLive(result); setLastLiveRefresh(new Date().toISOString()) }
      } catch (err) {
        if (active) setError('Live provider refresh failed. Historical observations remain available.')
      }
    }
    if (dataMode === 'REAL') {
      refreshLive()
      const timer = window.setInterval(refreshLive, 15 * 60 * 1000)
      return () => { active = false; window.clearInterval(timer) }
    }
    setLive(null)
    return () => { active = false }
  }, [dataMode, studyArea])

  useEffect(() => {
    let active = true
    let retryTimer: number | undefined
    setSatelliteIndexRows([])
    const end = new Date()
    const start = new Date(end)
    start.setDate(end.getDate() - Number(range))
    const params = new URLSearchParams({ study_area_id: studyArea })
    if (startDate && endDate) {
      params.set('start_date', startDate)
      params.set('end_date', endDate)
    } else {
      params.set('start_date', start.toISOString().slice(0, 10))
      params.set('end_date', end.toISOString().slice(0, 10))
    }
    const loadObservations = async () => {
      try {
        const response = await api.observations(params.toString())
        if (!active) return
        setDataMode(response.data_mode)
        let rows = response.observations
        setObservations(rows)
        setError('')
        if (response.data_mode === 'REAL') {
          const [vegetationResult, weatherResult, sarResult] = await Promise.allSettled([
            api.vegetation(params.toString()),
            api.weather(params.toString()),
            api.sentinel1(params.toString()),
          ])
          if (!active) return
          setSatelliteIndexRows(vegetationResult.status === 'fulfilled' ? vegetationResult.value.observations : [])
          const vegetationByDate = new Map(vegetationResult.status === 'fulfilled' ? vegetationResult.value.observations.map((row) => [row.date, row]) : [])
          const weatherByDate = new Map(weatherResult.status === 'fulfilled' ? weatherResult.value.observations.map((row) => [row.date, row]) : [])
          const sarByDate = new Map(sarResult.status === 'fulfilled' ? sarResult.value.observations.map((row) => [row.date, row]) : [])
          rows = rows.map((row) => {
            const index = vegetationByDate.get(row.date)
            const weather = weatherByDate.get(row.date)
            const sar = sarByDate.get(row.date)
            const numeric = (value: string | number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? value : null
            return {
              ...row,
              ndvi: numeric(index?.NDVI), ndmi: numeric(index?.NDMI), ndwi: numeric(index?.NDWI),
              evi: numeric(index?.EVI), savi: numeric(index?.SAVI),
              rainfall_mm: weather?.rainfall_mm ?? null,
              temperature_c: weather?.temperature_c ?? null,
              et0_mm: weather?.et0_mm ?? null,
              s1_vv: numeric(sar?.VV), s1_vh: numeric(sar?.VH),
            }
          })
          const unavailable: string[] = []
          if (vegetationResult.status === 'rejected') unavailable.push('Sentinel-2 indices')
          if (weatherResult.status === 'rejected') unavailable.push('weather')
          if (sarResult.status === 'rejected') unavailable.push('Sentinel-1 backscatter')
          setError(unavailable.length ? `${unavailable.join(', ')} service temporarily unavailable. Other returned sources remain separate; missing values are not estimated.` : '')
        } else {
          setSatelliteIndexRows([])
          setError('')
        }
        setObservations(rows)
      } catch {
        if (!active) return
        setObservations([])
        setSatelliteIndexRows([])
        setError('Data service temporarily unavailable. Retrying; no sample or estimated values are being shown.')
        retryTimer = window.setTimeout(() => { void loadObservations() }, 10000)
      }
    }
    void loadObservations()
    return () => {
      active = false
      if (retryTimer !== undefined) window.clearTimeout(retryTimer)
    }
  }, [range, studyArea, startDate, endDate, dataMode])

  useEffect(() => {
    if (page !== 'Weather & Rainfall') return
    const params = new URLSearchParams({ study_area_id: studyArea })
    if (startDate && endDate) {
      params.set('start_date', startDate)
      params.set('end_date', endDate)
    }
    api.weather(params.toString()).then((response) => setWeatherRows(response.observations)).catch(() => setWeatherRows([]))
    if (dataMode === 'REAL') {
      api.weather('forecast_days=7').then((response) => setForecastRows(response.observations)).catch(() => setForecastRows([]))
    } else {
      setForecastRows([])
    }
  }, [page, studyArea, startDate, endDate, dataMode])

  useEffect(() => {
    if (!latest) {
      setAdvisory(null)
      return
    }
    api.advisory(latest.date).then((result: AdvisoryResponse) => setAdvisory(result)).catch(() => setAdvisory(null))
  }, [latest?.date, dataMode, range, startDate, endDate, studyArea])

  useEffect(() => {
    if (!observations.length) return
    setDateA((current) => observations.some((row) => row.date === current) ? current : observations[Math.max(0, observations.length - 2)].date)
    setDateB((current) => observations.some((row) => row.date === current) ? current : observations[observations.length - 1].date)
  }, [observations])

  useEffect(() => {
    if (page === 'Soil Moisture') setLayer('soil_moisture')
    else if (page === 'Vegetation Indices') setLayer('ndvi')
    else if (page === 'Weather & Rainfall') setLayer('rainfall_mm')
    else if (page === 'Moisture Stress') setLayer('moisture_stress')
    else if (page === 'Crop Monitoring') setLayer('crop_type')
  }, [page])

  const showHome = page === 'Dashboard' || page === 'Reports' || presentation
  const showMap = showHome || ['Live Monitoring', 'Soil Moisture', 'Crop Monitoring', 'Vegetation Indices', 'Moisture Stress', 'Satellite Explorer'].includes(page)
  const showAdvisory = showHome || ['Live Monitoring', 'Moisture Stress', 'Irrigation Advisory'].includes(page)
  const showAnalytics = showHome || ['Historical Analysis', 'Soil Moisture', 'Weather & Rainfall', 'Vegetation Indices'].includes(page)
  const showAssistant = showHome || page === 'AI Insights'
  const showRecords = showHome || ['Historical Analysis', 'Soil Moisture', 'Crop Monitoring', 'Moisture Stress'].includes(page)
  const means = useMemo(() => {
    const average = (key: keyof Observation) => {
      const values = observations.map((row) => row[key]).filter((value): value is number => typeof value === 'number')
      return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
    }
    return { moisture: average('soil_moisture'), rainfall: average('rainfall_mm'), ndvi: average('ndvi'), temperature: average('temperature_c'), et0: average('et0_mm') }
  }, [observations])
  const chartObservations = useMemo(() => {
    if (page !== 'Weather & Rainfall') return observations
    const weatherByDate = new Map(weatherRows.map((row) => [row.date, row]))
    return observations.map((row) => {
      const weather = weatherByDate.get(row.date)
      return weather ? { ...row, rainfall_mm: weather.rainfall_mm, temperature_c: weather.temperature_c, et0_mm: weather.et0_mm } : row
    })
  }, [observations, page, weatherRows])
  const filteredObservations = useMemo(() => {
    const query = tableSearch.trim().toLowerCase()
    return observations.filter((row) => !query || [row.date, row.crop, row.growth_stage, row.moisture_stress, row.irrigation_advisory].some((value) => value?.toLowerCase().includes(query)))
  }, [observations, tableSearch])
  const tablePageCount = Math.max(1, Math.ceil(filteredObservations.length / 8))
  const currentPage = Math.min(tablePage, tablePageCount - 1)

  function display(value: number | null, digits = 2, suffix = '') {
    return value == null ? 'Unavailable' : `${value.toFixed(digits)}${suffix}`
  }

  const metricCards = [
    { title: 'SOIL MOISTURE', value: display(liveSoilMoisture, 3), unit: 'm³/m³ · coarse regional product', icon: Droplets, color: 'mint' },
    { title: 'RAINFALL', value: display(liveRainfall, 1, ' mm'), unit: 'daily observation', icon: CloudSun, color: 'blue' },
    { title: 'VEGETATION · NDVI', value: display(latestNdvi, 2), unit: latestNdviDate ? `latest available · ${latestNdviDate}` : 'derived-index value unavailable', icon: Leaf, color: 'green' },
    { title: 'AIR TEMPERATURE', value: display(liveTemperature, 1, '°'), unit: 'weather service', icon: Activity, color: 'amber' },
    { title: 'REFERENCE ET₀', value: display(liveEt0, 1, ' mm'), unit: 'daily weather estimate', icon: Gauge, color: 'violet' },
    { title: 'MOISTURE STRESS', value: latest?.moisture_stress ?? 'Unavailable', unit: dataMode === 'DEMO' ? 'illustrative category · not model output' : 'model classification unavailable', icon: ShieldAlert, color: 'rose' },
  ]

  const content = <main className="main-content">
    <header className="topbar">
      <button className="mobile-menu icon-button" onClick={() => setMobileOpen(!mobileOpen)} aria-label="Toggle navigation">{mobileOpen ? <X size={19} /> : <Menu size={19} />}</button>
      <div className="breadcrumb">Workspace <span>/</span> <b>{page}</b></div>
      <div className="topbar-right">
        <label className="area-picker"><span>STUDY AREA</span><select value={studyArea} onChange={(event) => setStudyArea(event.target.value)} aria-label="Select study area">{studyAreas.length ? studyAreas.map((area) => <option key={area.id} value={area.id}>{area.name}, {area.region}</option>) : <option value="mehsana">Study area unavailable</option>}</select><ChevronDown size={14} /></label>
        <button className={`presentation-toggle ${presentation ? 'active' : ''}`} onClick={() => setPresentation(!presentation)}>{presentation ? 'Exit presentation' : 'Presentation mode'}</button>
        <button className="icon-button notification" aria-label="Notifications"><Bell size={18} /><i /></button>
        <div className="avatar" aria-label="Research workspace">AS</div>
      </div>
    </header>
    <div className="content-wrap">
      <div className="page-heading">
        <div><div className="eyebrow">SMART IRRIGATION & REMOTE SENSING PLATFORM</div><h1>{presentation ? 'AgroSense AI · Research presentation' : page === 'Dashboard' ? greeting : page}</h1><p>Satellite-informed water monitoring for Mehsana district, Gujarat. Latest available record: {latest?.date ?? 'Unavailable'}.</p></div>
        <div className="heading-controls"><span className={`demo-badge ${dataMode === 'REAL' ? 'real-mode' : ''}`}><i /> {dataModeLabel} MODE</span>{page === 'Historical Analysis' && <><label className="date-range"><span>DATE A</span><select value={dateA} onChange={(event) => setDateA(event.target.value)} aria-label="Select comparison date A"><option value="">Select date</option>{observations.map((row) => <option key={`a-${row.date}`} value={row.date}>{row.date}</option>)}</select></label><label className="date-range"><span>DATE B</span><select value={dateB} onChange={(event) => setDateB(event.target.value)} aria-label="Select comparison date B"><option value="">Select date</option>{observations.map((row) => <option key={`b-${row.date}`} value={row.date}>{row.date}</option>)}</select></label></>}{page === 'Historical Analysis' && <label className="date-range"><span>FROM</span><input aria-label="Start date" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>}{page === 'Historical Analysis' && <label className="date-range"><span>TO</span><input aria-label="End date" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>}{page !== 'Historical Analysis' && <label className="date-range"><span>PERIOD</span><select value={range} onChange={(event) => { setRange(event.target.value); setStartDate(''); setEndDate('') }} aria-label="Select date range"><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option></select></label>}</div>
      </div>
      <div className="science-note"><FlaskConical size={16} /><span><b>{dataMode === 'DEMO' ? 'Transparent demo data' : dataMode === 'REAL' ? 'Transparent real-data mode' : 'Connecting to configured data mode'}</b> — {dataMode === 'DEMO' ? 'displayed observations and map locations are labeled sample records, not live satellite measurements.' : dataMode === 'REAL' ? 'provider data is shown only when returned; missing observations remain unavailable.' : 'No live observations are rendered until the backend reports its data mode.'} SMAP represents coarse regional soil-moisture information, not field-scale sensing.</span></div>
      {dataMode === 'REAL' && <div className="science-note"><Radio size={16} /><span><b>LIVE PROVIDER REFRESH</b> — weather/current conditions refresh every 15 minutes; satellite values show the latest available SMAP observation. {lastLiveRefresh ? `Last refresh: ${new Date(lastLiveRefresh).toLocaleTimeString()}` : 'Connecting...'}</span></div>}
      {error && <div className="error-banner" role="alert">{error}</div>}
      {(showHome || page === 'Live Monitoring') && <section className="kpi-grid" aria-label="Environmental summary">{metricCards.map((card) => {
        const Icon = card.icon
        return <article className="kpi-card" key={card.title}><div className={`kpi-icon ${card.color}`}><Icon size={19} /></div><div className="kpi-label">{card.title}</div><div className="kpi-value">{card.value}</div><div className="kpi-unit">{card.unit}</div><div className="kpi-source">{dataModeLabel} DATA</div></article>
      })}</section>}
      {page === 'Historical Analysis' && <section className="comparison-card"><div className="eyebrow">DATE-WISE COMPARISON</div><h2>Previous observation · selected date</h2>{(() => { const left = observations.find((row) => row.date === dateA); const right = observations.find((row) => row.date === dateB); const fields: [string, keyof Observation][] = [['Soil moisture', 'soil_moisture'], ['Rainfall', 'rainfall_mm'], ['NDVI', 'ndvi'], ['NDMI', 'ndmi'], ['Temperature', 'temperature_c'], ['ET₀', 'et0_mm']]; return <div className="comparison-grid">{fields.map(([label, key]) => { const a = left?.[key]; const b = right?.[key]; const delta = typeof a === 'number' && typeof b === 'number' ? b - a : null; const change = delta === null ? 'Change unavailable' : delta > 0 ? `Increase ${delta.toFixed(3)}` : delta < 0 ? `Decrease ${Math.abs(delta).toFixed(3)}` : 'No change'; return <div className="comparison-item" key={label}><span>{label}</span><b>{typeof a === 'number' ? a.toFixed(3) : 'Unavailable'} <i>→</i> {typeof b === 'number' ? b.toFixed(3) : 'Unavailable'}</b><small>{change} · {dateA || 'Date A'} → {dateB || 'Date B'}; no unavailable values are estimated</small></div> })}</div> })()}</section>}
      {page === 'Weather & Rainfall' && <section className="weather-card"><div className="eyebrow">WEATHER OBSERVATIONS</div><h2>Rainfall, temperature & evapotranspiration</h2><p>{dataMode === 'DEMO' ? 'Labeled demonstration weather records; forecast unavailable in demo mode.' : dataMode === 'REAL' ? 'Open-Meteo archive observations are shown separately from the seven-day forecast below.' : 'Connecting to weather source; unavailable values are not estimated.'}</p><h3>Historical / demo observations</h3><div className="weather-grid">{weatherRows.slice(-5).map((row) => <article key={row.date}><b>{row.date}</b><span>Rainfall <strong>{row.rainfall_mm == null ? 'Unavailable' : `${row.rainfall_mm.toFixed(1)} mm`}</strong></span><span>Temperature <strong>{row.temperature_c == null ? 'Unavailable' : `${row.temperature_c.toFixed(1)}°C`}</strong></span><span>Humidity <strong>{row.humidity_pct == null ? 'Unavailable' : `${row.humidity_pct}%`}</strong></span><span>Wind <strong>{row.wind_kmh == null ? 'Unavailable' : `${row.wind_kmh.toFixed(1)} km/h`}</strong></span><span>ET₀ <strong>{row.et0_mm == null ? 'Unavailable' : `${row.et0_mm.toFixed(1)} mm`}</strong></span><small>{row.forecast ? 'FORECAST' : row.data_mode} · {row.source}</small></article>)}{weatherRows.length === 0 && <div className="empty-state">Weather service temporarily unavailable or no records for selected dates.</div>}</div><h3>Seven-day forecast</h3>{dataMode === 'DEMO' ? <div className="empty-state forecast-unavailable">Forecast unavailable in demo mode. Enable a real weather provider to view forecasts.</div> : dataMode === null ? <div className="empty-state forecast-unavailable">Forecast availability is checked after the data mode loads.</div> : <div className="weather-grid">{forecastRows.map((row) => <article key={row.date}><b>{row.date}</b><span>Rain <strong>{row.rainfall_mm == null ? 'Unavailable' : `${row.rainfall_mm.toFixed(1)} mm`}</strong></span><span>Rain probability <strong>{row.rain_probability == null ? 'Unavailable' : `${row.rain_probability}%`}</strong></span><span>Temperature <strong>{row.temperature_c == null ? 'Unavailable' : `${row.temperature_c.toFixed(1)}°C`}</strong></span><small>FORECAST · {row.source}</small></article>)}{forecastRows.length === 0 && <div className="empty-state">Weather service temporarily unavailable.</div>}</div>}<div className="advisory-disclaimer">Weather forecasts are uncertain; do not interpret archive observations as a forecast.</div></section>}
      {page === 'Crop Monitoring' && <CropTrainingPanel canTrain={dataMode === 'REAL'} onModelTrained={() => setCropModelVersion((version) => version + 1)} />}
      {page === 'Moisture Stress' && <section className="model-note"><div className="eyebrow">STRESS MODEL STATUS</div><h2>No validated moisture-stress model is configured</h2><p>Demo status labels and rules are for interface demonstration. No stress score or confidence is reported without a trained, independently evaluated model.</p><span className="demo-badge"><i /> {dataMode === 'DEMO' ? 'DEMO LABELS' : 'MODEL UNAVAILABLE'}</span></section>}
      {(page === 'Reports' || page === 'Settings') && <section className="model-note"><div className="eyebrow">{page === 'Reports' ? 'RESEARCH REPORT' : 'APPLICATION CONFIGURATION'}</div><h2>{page === 'Reports' ? 'Presentation-ready project summary' : 'Data providers & display settings'}</h2><p>{page === 'Reports' ? 'AgroSense AI · Mehsana District, Gujarat · Sources: NASA SMAP (coarse regional product), Sentinel-1 SAR backscatter, cloud-filtered Sentinel-2 indices and weather where configured. Methods: satellite preprocessing, vegetation indicators, explainable rule-based advisory. Limitations: demo data is synthetic; model validation, local thresholds, field boundary and ground-truth data are not configured.' : `Current backend mode: ${dataModeLabel}. Change DATA_MODE in the backend environment and restart the API to switch modes. Earth Engine project, service credentials and weather sources are configured server-side; secrets are never sent to the browser.`}</p>{page === 'Reports' && <button className="export-button" onClick={() => window.print()}><FileText size={15} /> Print / save as PDF</button>}{page === 'Settings' && <div className="settings-grid"><span>Map layer <select value={layer} onChange={(event) => setLayer(event.target.value)}><option value="soil_moisture">Soil moisture</option><option value="ndvi">NDVI</option><option value="ndmi">NDMI</option><option value="ndwi">NDWI</option><option value="s1_vv">Sentinel-1 VV</option><option value="s1_vh">Sentinel-1 VH</option><option value="rainfall_mm">Rainfall</option><option value="moisture_stress">Moisture stress</option><option value="irrigation_advisory">Irrigation advisory</option></select></span><span>Observation window <select value={range} onChange={(event) => { setRange(event.target.value); setStartDate(''); setEndDate('') }}><option value="7">7 days</option><option value="30">30 days</option><option value="90">90 days</option></select></span></div>}</section>}
      {showMap && <div className={`overview-grid ${page === 'Crop Monitoring' ? 'crop-overview-grid' : ''}`}><MapPanel observations={observations} layer={layer} onLayerChange={setLayer} isDemo={dataMode !== 'REAL'} center={mapCenter} areaName={activeStudyArea?.name ?? 'Study area'} boundary={activeStudyArea?.boundary} cropModelVersion={cropModelVersion} />{showAdvisory && <section className="advisory-card"><div className="advisory-top"><span className="advisory-icon"><Waves size={18} /></span><span className={`demo-badge compact ${dataMode === 'REAL' ? 'real-mode' : ''}`}>{dataModeLabel}</span></div><div className="eyebrow">IRRIGATION DECISION SUPPORT</div><h2>{advisory?.status ?? 'Advisory unavailable'}</h2><p>{advisory?.reason ?? 'Advisory unavailable for the selected observation.'}</p><div className="advisory-divider" /><h3>Why this status?</h3><div className="factor"><span>Soil-moisture observation</span><b>{display(liveSoilMoisture, 3)}</b></div><div className="factor"><span>Rainfall</span><b>{display(latest?.rainfall_mm ?? null, 1, ' mm')}</b></div><div className="factor"><span>Crop / growth stage</span><b>{latest?.crop ?? 'Unavailable'} · {latest?.growth_stage ?? 'Unavailable'}</b></div><div className="advisory-disclaimer">Advisory support only — verify field conditions before irrigation.</div></section>}</div>}
      {showAnalytics && <div className="analysis-grid"><Analytics observations={chartObservations} isDemo={dataMode === 'DEMO'} />{showAssistant && <Assistant isDemo={dataMode === 'DEMO'} studyAreaId={studyArea} startDate={assistantStart} endDate={assistantEnd} />}</div>}
      {!showAnalytics && showAssistant && <Assistant isDemo={dataMode === 'DEMO'} studyAreaId={studyArea} startDate={assistantStart} endDate={assistantEnd} />}
      {showRecords && <section className="records-card"><div className="records-heading"><div><div className="eyebrow">OBSERVATION REGISTER</div><h2>{dataMode === 'DEMO' ? 'Recent demo records' : 'Recent available observations'}</h2></div><div className="table-tools"><label className="table-search"><Search size={14} /><input value={tableSearch} onChange={(event) => { setTableSearch(event.target.value); setTablePage(0) }} placeholder="Search observations" aria-label="Search observations" /></label><button className="export-button" onClick={() => {
        const header = ['Date', 'Latitude', 'Longitude', 'Soil moisture', 'Rainfall', 'Temperature', 'NDVI', 'NDMI', 'ET0', 'Crop', 'Growth stage', 'Stress', 'Advisory', 'Data mode']
        const rows = observations.map((row) => [row.date, row.latitude, row.longitude, row.soil_moisture ?? '', row.rainfall_mm ?? '', row.temperature_c ?? '', row.ndvi ?? '', row.ndmi ?? '', row.et0_mm ?? '', row.crop ?? '', row.growth_stage ?? '', row.moisture_stress ?? '', row.irrigation_advisory ?? '', row.data_mode])
        const csv = [header, ...rows].map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\n')
        const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
        const link = document.createElement('a'); link.href = url; link.download = 'agrosense-demo-observations.csv'; link.click(); URL.revokeObjectURL(url)
      }}><FileText size={15} /> Export CSV</button></div></div>
        <div className="table-scroll"><table><thead><tr><th>DATE</th><th>SOIL MOISTURE</th><th>RAINFALL</th><th>NDVI</th><th>CROP / STAGE</th><th>STRESS</th><th>ADVISORY</th><th>MODE</th></tr></thead><tbody>{filteredObservations.slice(currentPage * 8, currentPage * 8 + 8).reverse().map((row) => <tr key={`${row.date}-${row.latitude}`}><td>{row.date}</td><td>{display(row.soil_moisture, 3)}</td><td>{display(row.rainfall_mm, 1, ' mm')}</td><td>{display(row.ndvi, 2)}</td><td>{row.crop ?? 'Unavailable'}<small>{row.growth_stage ?? 'Unavailable'}</small></td><td><span className={`stress-chip ${row.moisture_stress === 'High Stress' ? 'high' : row.moisture_stress === 'Moderate Stress' ? 'moderate' : ''}`}>{row.moisture_stress ?? 'Unavailable'}</span></td><td>{row.irrigation_advisory ?? 'Unavailable'}</td><td><span className="table-demo">{row.data_mode}</span></td></tr>)}</tbody></table>{filteredObservations.length === 0 && <div className="empty-state">Data unavailable for selected date range.</div>}</div>
        <div className="table-pagination"><span>Showing {filteredObservations.length ? currentPage * 8 + 1 : 0}–{Math.min((currentPage + 1) * 8, filteredObservations.length)} of {filteredObservations.length} records</span><div><button disabled={currentPage === 0} onClick={() => setTablePage((value) => Math.max(0, value - 1))}>Previous</button><button disabled={currentPage + 1 >= tablePageCount} onClick={() => setTablePage((value) => Math.min(tablePageCount - 1, value + 1))}>Next</button></div></div>
        <div className="table-caption">Aggregated KPI averages: moisture {display(means.moisture, 3)}, rainfall {display(means.rainfall, 1, ' mm')}, NDVI {display(means.ndvi, 2)}, ET₀ {display(means.et0, 1, ' mm')}.</div>
      </section>}
      <footer className="footer"><span>AGROSENSE AI <i>·</i> Research prototype</span><span>Data status: {dataModeLabel} <i>·</i> Provider and model availability are reported separately.</span></footer>
    </div>
  </main>

  return <div className={`app-shell ${presentation ? 'presentation-mode' : ''}`}>
    <aside className={`sidebar ${mobileOpen ? 'open' : ''}`}>
      <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setPage('Dashboard') }}><div className="brand-icon"><Sprout size={22} /></div><div><b>AgroSense<span>AI</span></b><small>EARTH OBSERVATION PLATFORM</small></div></a>
      <div className="sidebar-area"><div className="area-marker" /><div><b>Mehsana district</b><small>Gujarat, India · 23.59°N, 72.37°E</small></div><ChevronDown size={15} /></div>
      <nav aria-label="Main navigation">{navigation.map((section) => <div className="nav-group" key={section.group}><div className="nav-heading">{section.group}</div>{section.items.map(([label, Icon]) => <button className={`nav-link ${page === label ? 'selected' : ''}`} key={label} onClick={() => { setPage(label); setMobileOpen(false) }}><Icon size={17} strokeWidth={1.8} /><span>{label}</span>{label === 'Live Monitoring' && <i className="live-indicator" />}</button>)}</div>)}</nav>
      <div className="sidebar-spacer" /><div className="sidebar-status"><div className="status-row"><i className="status-dot" /><span>{dataMode === 'DEMO' ? 'Demo environment' : dataMode === 'REAL' ? 'Real-data mode' : 'Connecting to API'}</span><span className="demo-mini">{dataModeLabel}</span></div><div className="status-sources"><span>SMAP</span><span>S1 · S2</span><span>WEATHER</span></div><p>{dataMode === 'DEMO' ? 'No live provider connection' : dataMode === 'REAL' ? 'Provider availability checked per request' : 'Data mode is not assumed'}</p></div><button className="sidebar-settings" onClick={() => setPage('Settings')}><Settings size={16} /> Settings <span>⌘ ,</span></button>
      <div className="sidebar-profile"><div className="profile-avatar">AR</div><div><b>Agri Research</b><small>Project workspace</small></div><Search size={16} /></div>
    </aside>
    {content}
  </div>
}

export default App
