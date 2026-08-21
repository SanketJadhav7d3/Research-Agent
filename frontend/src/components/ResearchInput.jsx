import { useEffect, useState } from 'react'
import { fetchProviders, improvePrompt } from '../lib/api'

// The first two draw charts, because market data comes back as figures the
// agent can plot directly. The last two do not, and that is deliberate: a
// question with nothing numeric in it should produce prose and no chart, and
// the demo is more honest for showing both.
const EXAMPLES = [
  'Compare Nvidia, AMD and Intel on valuation and profitability',
  'How does Apple’s margin profile compare with Microsoft’s?',
  'What are the key risks of the EU AI Act for LLM startups?',
  'What happened to SVB and what were the regulatory consequences?',
]

const LABELS = {
  google_genai: 'Google Gemini',
  openai: 'OpenAI',
  anthropic: 'Anthropic Claude',
}

// "ai act, gdpr" -> ["ai act", "gdpr"]
const parseTerms = (raw) =>
  raw.split(',').map((t) => t.trim()).filter(Boolean)

export default function ResearchInput({ onStart, onStop, status }) {
  const [goal, setGoal] = useState('')
  const [providers, setProviders] = useState(null)
  const [provider, setProvider] = useState('')
  const [apiKey, setApiKey] = useState('')

  const [include, setInclude] = useState('')
  const [exclude, setExclude] = useState('')
  const [showFilters, setShowFilters] = useState(false)

  const [improving, setImproving] = useState(false)
  // Set only while a rewrite is on screen, so it can be reverted.
  const [improvement, setImprovement] = useState(null)

  useEffect(() => {
    fetchProviders()
      .then((p) => {
        setProviders(p)
        setProvider(p.default)
      })
      .catch(() => setProviders(null))
  }, [])

  const running = status === 'running'
  // A rewrite in flight will replace whatever is in the box when it lands, so
  // everything that reads or writes the goal is held until it does. Otherwise
  // a user can start a run against text that is about to change under them, or
  // lose what they were typing.
  const busy = running || improving
  const needsKey = providers && provider && provider !== providers.default
  const credentials = needsKey ? { provider, api_key: apiKey } : {}

  const setGoalManually = (text) => {
    setGoal(text)
    setImprovement(null)
  }

  const improve = async () => {
    const text = goal.trim()
    if (!text || improving || running) return
    setImproving(true)
    try {
      const result = await improvePrompt({ goal: text, ...credentials })
      setImprovement({ original: text, changes: result.changes ?? [] })
      setGoal(result.improved)
    } catch (err) {
      setImprovement({ error: err.message })
    } finally {
      setImproving(false)
    }
  }

  const undoImprovement = () => {
    if (improvement?.original) setGoal(improvement.original)
    setImprovement(null)
  }

  const submit = (e) => {
    e.preventDefault()
    if (!goal.trim() || busy) return
    onStart({
      goal: goal.trim(),
      provider: needsKey ? provider : undefined,
      apiKey: needsKey ? apiKey : undefined,
      includeKeywords: parseTerms(include),
      excludeKeywords: parseTerms(exclude),
    })
  }

  const filterCount = parseTerms(include).length + parseTerms(exclude).length

  return (
    <form className="input-card" onSubmit={submit}>
      <textarea
        value={goal}
        onChange={(e) => setGoalManually(e.target.value)}
        placeholder="Ask a research question…"
        rows={3}
        disabled={busy}
      />

      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button key={ex} type="button" className="chip"
                  onClick={() => setGoalManually(ex)} disabled={busy}>
            {ex.length > 52 ? `${ex.slice(0, 52)}…` : ex}
          </button>
        ))}
      </div>

      {improvement?.error && (
        <p className="improve-note error">
          Could not improve the prompt — {improvement.error}
        </p>
      )}

      {improvement && !improvement.error && (
        <div className="improve-note">
          <div className="improve-head">
            <span>✨ Rewritten</span>
            <button type="button" className="linky" onClick={undoImprovement}>
              Undo
            </button>
          </div>
          {improvement.changes.length > 0 ? (
            <ul>
              {improvement.changes.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          ) : (
            <p>The question was already clear — barely changed.</p>
          )}
        </div>
      )}

      {showFilters && (
        <div className="filters">
          <label>
            <span>Prefer these terms</span>
            <input
              type="text"
              value={include}
              onChange={(e) => setInclude(e.target.value)}
              placeholder="e.g. regulation, enforcement"
              disabled={running}
            />
          </label>
          <label>
            <span>Exclude these terms</span>
            <input
              type="text"
              value={exclude}
              onChange={(e) => setExclude(e.target.value)}
              placeholder="e.g. crypto, opinion"
              disabled={running}
            />
          </label>
          <p className="hint">
            Comma-separated. Preferred terms are added to the agent's searches
            to steer them; excluded terms are enforced — matching results are
            dropped before the agent sees them.
          </p>
        </div>
      )}

      <div className="controls">
        <button
          type="button"
          className="ghost"
          onClick={improve}
          disabled={!goal.trim() || busy}
          title="Rewrite the question to be clearer and more specific"
        >
          {improving ? 'Improving…' : '✨ Improve'}
        </button>

        <button
          type="button"
          className={showFilters ? 'ghost active' : 'ghost'}
          onClick={() => setShowFilters((v) => !v)}
          disabled={improving}
        >
          Filters{filterCount > 0 && ` · ${filterCount}`}
        </button>

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
          <button type="submit" disabled={!goal.trim() || improving}>
            {improving ? 'Improving…' : 'Research'}
          </button>
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
