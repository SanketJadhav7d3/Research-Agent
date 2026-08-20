import { useEffect, useState } from 'react'
import { fetchProviders } from '../lib/api'

const EXAMPLES = [
  'What are the key risks of the EU AI Act for LLM startups?',
  'What happened to SVB and what were the regulatory consequences?',
  'Compare the revenue models of Anthropic, OpenAI and Mistral',
]

const LABELS = {
  google_genai: 'Google Gemini',
  openai: 'OpenAI',
  anthropic: 'Anthropic Claude',
}

export default function ResearchInput({ onStart, onStop, status }) {
  const [goal, setGoal] = useState('')
  const [providers, setProviders] = useState(null)
  const [provider, setProvider] = useState('')
  const [apiKey, setApiKey] = useState('')

  useEffect(() => {
    fetchProviders()
      .then((p) => {
        setProviders(p)
        setProvider(p.default)
      })
      .catch(() => setProviders(null))
  }, [])

  const running = status === 'running'
  const needsKey = providers && provider && provider !== providers.default

  const submit = (e) => {
    e.preventDefault()
    if (!goal.trim() || running) return
    onStart({
      goal: goal.trim(),
      provider: needsKey ? provider : undefined,
      apiKey: needsKey ? apiKey : undefined,
    })
  }

  return (
    <form className="input-card" onSubmit={submit}>
      <textarea
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
        placeholder="Ask a research question…"
        rows={3}
        disabled={running}
      />

      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button key={ex} type="button" className="chip"
                  onClick={() => setGoal(ex)} disabled={running}>
            {ex.length > 52 ? `${ex.slice(0, 52)}…` : ex}
          </button>
        ))}
      </div>

      <div className="controls">
        {providers && (
          <select value={provider} onChange={(e) => setProvider(e.target.value)}
                  disabled={running}>
            {providers.supported.map((p) => (
              <option key={p} value={p}>
                {LABELS[p] ?? p}{p === providers.default ? ' — no key needed' : ''}
              </option>
            ))}
          </select>
        )}

        {needsKey && (
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={`Your ${LABELS[provider] ?? provider} API key`}
            disabled={running}
          />
        )}

        {running ? (
          <button type="button" className="stop" onClick={onStop}>Stop</button>
        ) : (
          <button type="submit" disabled={!goal.trim()}>Research</button>
        )}
      </div>

      {needsKey && (
        <p className="hint">
          Your key is used for this request only. It is never stored or logged.
        </p>
      )}
    </form>
  )
}
