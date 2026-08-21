// Confidence across research rounds. Showing every round rather than only the
// last makes the loop-back visible: you can see a weak first pass improve.
export default function ConfidenceBar({ history }) {
  if (!history?.length) return null

  const latest = history[history.length - 1]
  const pct = Math.round((latest.score ?? 0) * 100)
  // green above the gate threshold, amber mid, red when the evidence is thin
  const colour =
    pct >= 75 ? 'var(--green)' : pct >= 45 ? 'var(--ochre)' : 'var(--red)'

  return (
    <div className="confidence">
      <div className="confidence-head">
        <span>
          Agent confidence
          {history.length > 1 && (
            <span className="round-tag"> · round {history.length}</span>
          )}
        </span>
        <strong style={{ color: colour }}>{pct}%</strong>
      </div>

      <div className="confidence-track">
        <div className="confidence-fill"
             style={{ width: `${pct}%`, background: colour }} />
      </div>

      {history.length > 1 && (
        <div className="confidence-history">
          {history.map((h, i) => (
            <span key={i} className="round-pip">
              R{i + 1}: {Math.round((h.score ?? 0) * 100)}%
              {i < history.length - 1 && ' →'}
            </span>
          ))}
        </div>
      )}

      {latest.reason && <p className="confidence-reason">{latest.reason}</p>}

      {latest.gaps?.length > 0 && (
        <ul className="gaps">
          {latest.gaps.map((g, i) => <li key={i}>{g}</li>)}
        </ul>
      )}
    </div>
  )
}
