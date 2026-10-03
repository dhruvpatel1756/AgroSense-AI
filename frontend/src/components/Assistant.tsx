import { useState } from 'react'
import { ArrowUp, Bot, Sparkles } from 'lucide-react'
import { api } from '../services/api'

const suggestions = ['Why is irrigation being recommended?', 'How did soil moisture change?', 'Which locations show stress?']

export default function Assistant({ isDemo, studyAreaId, startDate, endDate }: { isDemo: boolean; studyAreaId: string; startDate: string; endDate: string }) {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [evidence, setEvidence] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  async function ask(text: string) {
    if (!text.trim()) return
    setQuestion(text)
    setLoading(true)
    try {
      const result = await api.insights(text, studyAreaId, startDate, endDate)
      setAnswer(result.answer)
      setEvidence(result.evidence)
    } catch {
      setAnswer("I don't have sufficient data for this location/date.")
      setEvidence([])
    } finally { setLoading(false) }
  }
  return <section className="assistant-card">
    <div className="assistant-top"><div className="assistant-icon"><Bot size={19} /></div><div><h2>Ask AgroSense AI</h2><p>Answers use available application data only</p></div><Sparkles size={17} className="sparkle" /></div>
    <div className="suggestions">{suggestions.map((item) => <button key={item} onClick={() => void ask(item)}>{item}</button>)}</div>
    {answer && <div className="assistant-answer" aria-live="polite"><b>{question}</b><p>{loading ? 'Checking available records…' : answer}</p>{evidence.length > 0 && <ul>{evidence.map((item) => <li key={item}>{item}</li>)}</ul>}</div>}
    <form className="assistant-input" onSubmit={(event) => { event.preventDefault(); void ask(question) }}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about available observations…" aria-label="Ask AgroSense AI" /><button type="submit" aria-label="Send question" disabled={loading}><ArrowUp size={17} /></button></form>
    <div className="chart-footnote">{isDemo ? 'DEMO answers summarize demo records only.' : 'Answers use only records returned by the configured service.'} Gemini integration requires a server-side API key.</div>
  </section>
}
