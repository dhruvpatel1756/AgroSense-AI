import { useEffect, useState } from 'react'
import { Play, RefreshCw } from 'lucide-react'
import { api, type CropModelStatus } from '../services/api'

export default function CropTrainingPanel({ onModelTrained, canTrain }: { onModelTrained: () => void; canTrain: boolean }) {
  const [model, setModel] = useState<CropModelStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    api.cropModel().then((result) => {
      if (active) setModel(result)
    }).catch(() => {
      if (active) setError('Could not read crop-dataset status from the API.')
    })
    return () => { active = false }
  }, [])

  async function train() {
    setBusy(true)
    setError('')
    try {
      const result = await api.trainBundledCropModel()
      setModel(result)
      onModelTrained()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Crop-classifier training failed.')
    } finally {
      setBusy(false)
    }
  }

  const validation = model?.validation
  const belowBaseline = validation?.baseline_accuracy != null && validation.accuracy <= validation.baseline_accuracy

  return (
    <section className="crop-training-card">
      <div className="eyebrow">SUPERVISED CROP CLASSIFICATION</div>
      <h2>{model?.model_available ? 'Fennel and cotton classifier' : 'Train from the supplied Mahesana crop datasets'}</h2>
      <p>Uses the supplied Sentinel-2 field-feature CSVs and trains a Random Forest classifier with B2–B8A, B11/B12, NDVI and NDMI features.</p>

      {model?.dataset_available ? (
        <div className="crop-dataset-summary">
          <div><b>{model.dataset_rows}</b><span>feature records</span></div>
          {Object.entries(model.class_counts ?? {}).map(([crop, count]) => <div key={crop}><b>{count}</b><span>{crop} records</span></div>)}
          <small>{model.date_start} to {model.date_end} · {model.datasets?.join(' + ')}</small>
        </div>
      ) : <div className="empty-state">Bundled crop datasets are unavailable. Check the backend data/training files.</div>}

      <button className="export-button crop-train-button" type="button" onClick={train} disabled={busy || !canTrain || !model?.dataset_available}>
        {busy ? <><RefreshCw size={15} className="crop-training-spinner" /> Training classifier…</> : <><Play size={15} /> {model?.model_available ? 'Retrain crop classifier' : 'Train & evaluate crop classifier'}</>}
      </button>
      {!canTrain && <div className="advisory-disclaimer">Switch the backend to REAL mode and configure Earth Engine before training the satellite map classifier.</div>}
      {error && <div className="error-banner" role="alert">{error}</div>}

      {validation && (
        <div className="crop-model-result">
          <div className="crop-class-list">{model?.classes.map((crop) => <span key={crop.crop_type}><i style={{ backgroundColor: crop.color }} />{crop.crop_type}</span>)}</div>
          <div className="crop-validation">
            <b>5-fold stratified validation</b>
            <span>Accuracy: {(validation.accuracy * 100).toFixed(1)}%</span>
            <span>Majority-class baseline: {validation.baseline_accuracy == null ? 'Unavailable' : `${(validation.baseline_accuracy * 100).toFixed(1)}%`}</span>
            <span>Kappa: {validation.kappa == null ? 'Unavailable' : validation.kappa.toFixed(3)}</span>
          </div>
          <small>Confusion matrix (actual rows, predicted columns; {validation.class_order.join(', ')}): {validation.confusion_matrix.map((row) => `[${row.join(', ')}]`).join(' ')}. {validation.method}.</small>
          <div className={`crop-model-warning ${belowBaseline ? 'low-skill' : ''}`}>
            {belowBaseline
              ? 'Cross-validation accuracy does not exceed the majority-class baseline. The resulting map is experimental and must not be used as a validated crop inventory.'
              : 'Validation uses a random record split, not independent field polygons or a separate season. Treat map classes as exploratory, not field-verified.'}
          </div>
          <small>{model?.note}</small>
        </div>
      )}
      {!validation && <div className="advisory-disclaimer">The CSVs contain spectral features and crop labels but no field coordinates. The map can only show exploratory Sentinel-2 pixel predictions; independent geospatial ground truth is still needed to validate field boundaries and accuracy.</div>}
    </section>
  )
}
