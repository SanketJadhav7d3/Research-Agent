import { useEffect, useRef } from 'react'
import ToolCallCard from './ToolCallCard'

const NODE_LABELS = {
  clarify: 'Clarifying the question',
  plan: 'Planning sub-questions',
  execute: 'Gathering evidence',
  reflect: 'Judging its own answer',
  synthesize: 'Writing the report',
}

// Pairs each tool_call with the tool_result that follows it, so the trace shows
// one card per call rather than two disconnected events.
function buildRows(events) {
  const rows = []
  const pending = []

  for (const e of events) {
    if (e.name === 'node_start') {
      rows.push({ kind: 'node', node: e.node, timestamp: e.timestamp })
    } else if (e.name === 'tool_call') {
      const row = { kind: 'tool', call: e, result: null }
      rows.push(row)
      pending.push(row)
    } else if (e.name === 'tool_result') {
      const row = pending.find((r) => r.call.tool === e.tool && !r.result)
      if (row) row.result = e
    } else if (e.name === 'tool_skipped') {
      rows.push({ kind: 'skipped', event: e })
    } else if (e.name === 'gate') {
      rows.push({ kind: 'gate', gate: e })
    } else if (e.name === 'error') {
      rows.push({ kind: 'error', message: e.message })
    }
  }
  return rows
}

export default function AgentTrace({ events, status }) {
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [events.length])

  if (!events.length && status === 'idle') return null

  const rows = buildRows(events)

  return (
    <section className="trace">
      <h2 className="section-title">Agent trace</h2>

      {rows.map((row, i) => {
        if (row.kind === 'node') {
          return (
            <div key={i} className="trace-node">
              <span className="dot" />
              {NODE_LABELS[row.node] ?? row.node}
            </div>
          )
        }
        if (row.kind === 'skipped') {
          const v = Object.values(row.event.input ?? {})[0] ?? ''
          return (
            <div key={i} className="trace-skipped">
              ⤾ skipped duplicate {row.event.tool} — {String(v).slice(0, 60)}
            </div>
          )
        }
        if (row.kind === 'gate') {
          const g = row.gate
          const pct = Math.round((g.score ?? 0) * 100)
          return (
            <div key={i} className="trace-gate">
              {g.decision === 'execute'
                ? `↻ ${pct}% confidence — below ${Math.round(g.threshold * 100)}%, researching the gaps again`
                : g.reason === 'max_iterations'
                  ? `⚑ ${pct}% confidence — attempt limit reached, writing the report with its limitations stated`
                  : `✓ ${pct}% confidence — enough to write the report`}
            </div>
          )
        }
        if (row.kind === 'error') {
          return <div key={i} className="trace-error">⚠ {row.message}</div>
        }
        return <ToolCallCard key={i} call={row.call} result={row.result} />
      })}

      {status === 'running' && (
        <div className="trace-working"><span className="spinner" /> working…</div>
      )}
      <div ref={endRef} />
    </section>
  )
}
