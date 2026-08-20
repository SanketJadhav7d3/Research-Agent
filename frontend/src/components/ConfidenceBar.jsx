// Visual confidence indicator. Colour shifts red -> amber -> green with score,
// so a weak answer looks weak at a glance.
export default function ConfidenceBar({ confidence }) {
  if (!confidence) return null

  const pct = Math.round((confidence.score ?? 0) * 100)
  const colour = pct >= 75 ? 'var(--ok)' : pct >= 45 ? 'var(--warn)' : 'var(--bad)'

  return (
    <div className="confidence">
      <div className="confidence-head">
        <span>Agent confidence</span>
        <strong style={{ color: colour }}>{pct}%</strong>
      </div>
      <div className="confidence-track">
        <div
          className="confidence-fill"
          style={{ width: `${pct}%`, background: colour }}
        />
      </div>
      {confidence.reason && <p className="confidence-reason">{confidence.reason}</p>}
      {confidence.gaps?.length > 0 && (
        <ul className="gaps">
          {confidence.gaps.map((g, i) => <li key={i}>{g}</li>)}
        </ul>
      )}
    </div>
  )
}
