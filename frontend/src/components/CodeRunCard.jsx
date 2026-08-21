import { useState } from 'react'

// One run of agent-written code, collapsed by default.
//
// The code is worth showing rather than hiding: it is the audit trail for
// every chart in the report. If a figure looks wrong, this is where you see
// whether the number was read out of the evidence or typed by hand.
export default function CodeRunCard({ event }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="tool-card">
      <button className="tool-head" onClick={() => setOpen((o) => !o)}>
        <span className="tool-icon">🐍</span>
        <span className="tool-name">run_python</span>
        <span className="tool-query">{event.purpose}</span>
        <span className="tool-count">attempt {event.attempt}</span>
        <span className="tool-chevron">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="tool-body">
          <pre className="code-block">
            <code>{event.code}</code>
          </pre>
        </div>
      )}
    </div>
  )
}
