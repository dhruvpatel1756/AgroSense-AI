import { useMemo, useState } from 'react'
import { Download } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Observation } from '../types'

const metrics = {
  soil_moisture: { label: 'Soil moisture', color: '#56866c', unit: 'm³/m³' },
  rainfall_mm: { label: 'Rainfall', color: '#5a91b1', unit: 'mm' },
  temperature_c: { label: 'Temperature', color: '#c18c52', unit: '°C' },
  et0_mm: { label: 'ET₀', color: '#8776a4', unit: 'mm' },
  ndvi: { label: 'NDVI', color: '#86a75a', unit: 'index' },
  ndmi: { label: 'NDMI', color: '#5b998c', unit: 'index' },
  ndwi: { label: 'NDWI', color: '#5b8ab0', unit: 'index' },
  evi: { label: 'EVI', color: '#a17e56', unit: 'index' },
  savi: { label: 'SAVI', color: '#8a985a', unit: 'index' },
} as const

type Metric = keyof typeof metrics

export default function Analytics({ observations, isDemo }: { observations: Observation[]; isDemo: boolean }) {
  const [metric, setMetric] = useState<Metric>('soil_moisture')
  const config = metrics[metric]
  const chartData = useMemo(() => observations.map((row) => ({
    ...row,
    label: new Date(`${row.date}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }),
  })), [observations])
  const statistics = useMemo(() => {
    const values = observations.map((row) => row[metric]).filter((value): value is number => typeof value === 'number')
    return values.length
      ? { min: Math.min(...values), max: Math.max(...values), mean: values.reduce((sum, value) => sum + value, 0) / values.length }
      : null
  }, [observations, metric])

  function exportChartData() {
    const rows = [
      ['date', metric, 'unit', 'data_mode', 'source'],
      ...observations.map((row) => [row.date, row[metric] ?? '', config.unit, row.data_mode, row.source]),
    ]
    const csv = rows.map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `agrosense-${metric}-history.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="chart-card">
      <div className="chart-heading">
        <div><div className="eyebrow">OBSERVATION HISTORY</div><h2>Environmental trends</h2><p>{isDemo ? 'DEMO sample series · not measured satellite/weather observations' : 'Configured provider records · source shown in API response'}</p></div>
        <div className="chart-controls">
          <label className="sr-only" htmlFor="chart-metric">Chart metric</label>
          <select id="chart-metric" value={metric} onChange={(event) => setMetric(event.target.value as Metric)} aria-label="Chart metric">
            {Object.entries(metrics).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}
          </select>
          <button className="chart-export" onClick={exportChartData} disabled={!observations.length} aria-label="Export chart data as CSV"><Download size={14} /> Export</button>
        </div>
      </div>
      <div className="chart-area">
        {chartData.length === 0
          ? <div className="empty-state">Data unavailable for selected date range.</div>
          : <ResponsiveContainer width="100%" height="100%"><AreaChart data={chartData} margin={{ top: 10, right: 10, left: -14, bottom: 0 }}>
            <defs><linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={config.color} stopOpacity={0.22} /><stop offset="95%" stopColor={config.color} stopOpacity={0.01} /></linearGradient></defs>
            <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#e9ede8" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: '#849088', fontSize: 14 }} />
            <YAxis tickLine={false} axisLine={false} tick={{ fill: '#849088', fontSize: 14 }} domain={['auto', 'auto']} />
            <Tooltip contentStyle={{ borderRadius: 12, border: '1px solid #e6ebe5', fontSize: 15 }} formatter={(value) => [typeof value === 'number' ? `${value.toFixed(3)} ${config.unit}` : value, config.label]} />
            <Area type="monotone" dataKey={metric} stroke={config.color} strokeWidth={2.5} fill="url(#trendFill)" connectNulls={false} dot={{ r: 3, fill: config.color, strokeWidth: 0 }} />
          </AreaChart></ResponsiveContainer>}
      </div>
      <div className="chart-statistics">
        {(['min', 'mean', 'max'] as const).map((key) => <div key={key}><span>{key}</span><b>{statistics ? statistics[key].toFixed(3) : 'Unavailable'}</b></div>)}
        <span>{statistics ? `${observations.filter((row) => typeof row[metric] === 'number').length} available values` : 'No values for selected period'}</span>
      </div>
      <div className="chart-footnote">{metric === 'ndvi' ? 'NDVI is a relative vegetation indicator; interpretation depends on crop, season, soil and atmospheric conditions. No crop-specific condition threshold is configured.' : ''} Source: {isDemo ? 'labeled demonstration dataset · values are illustrative only.' : 'configured observation service · no unavailable values are interpolated.'}</div>
    </section>
  )
}
