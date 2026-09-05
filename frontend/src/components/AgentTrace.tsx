import { useEffect, useRef } from 'react'
import ToolCallCard from './ToolCallCard'
import CodeRunCard from './CodeRunCard'
import type {
  AgentEvent, AgentStatus, ChartReadyEvent, CodeRunEvent, GateEvent, MergedEvent,
  ResultsFilteredEvent, SubagentDoneEvent, ToolCallEvent, ToolResultEvent,
  ToolSkippedEvent,
} from '../types'

const NODE_LABELS: Record<string, string> = {
  clarify: 'Clarifying the question',
  plan: 'Planning sub-questions',
  execute: 'Gathering evidence',
  visualize: 'Writing code to chart the evidence',
  reflect: 'Judging its own answer',
  synthesize: 'Writing the report',
}

// Rows that can appear either at the top level or inside one agent's lane.
type InnerRow =
  | { kind: 'tool'; call: ToolCallEvent; result: ToolResultEvent | null }
  | { kind: 'filtered'; event: ResultsFilteredEvent }
  | { kind: 'skipped'; event: ToolSkippedEvent }

interface Lane {
  agent: string
  question: string
  rows: InnerRow[]
  done: SubagentDoneEvent | null
}

type Row =
  | { kind: 'node'; node: string; timestamp?: string }
  | InnerRow
  | { kind: 'fanout'; budget: number; lanes: Lane[]; merged: MergedEvent | null }
  | { kind: 'code'; event: CodeRunEvent }
  | { kind: 'chart'; event: ChartReadyEvent }
  | { kind: 'gate'; gate: GateEvent }
  | { kind: 'error'; message: string }

// Flattens the event stream into rows, pairing each tool_call with the
// tool_result that follows it so the trace shows one card per call.
//
// While Execute has fanned out, agent-tagged events are routed into that
// agent's lane instead of the flat list — the agents run concurrently, so a
// single chronological list interleaves three unrelated investigations and
// reads as noise. `fanout` opens the group and the next `node_start` closes it.
function buildRows(events: AgentEvent[]): Row[] {
  const rows: Row[] = []
  // Keyed by `${agent}|${tool}` so two agents searching at once cannot claim
  // each other's results.
  const pending = new Map<string, Extract<InnerRow, { kind: 'tool' }>[]>()
  let group: Extract<Row, { kind: 'fanout' }> | null = null
  let lanes = new Map<string, Lane>()

  const push = (row: InnerRow, agent?: string) => {
    const lane = agent ? lanes.get(agent) : undefined
    if (lane) lane.rows.push(row)
    else rows.push(row)
  }

  const queue = (row: Extract<InnerRow, { kind: 'tool' }>, agent?: string) => {
    const key = `${agent ?? ''}|${row.call.tool}`
    const list = pending.get(key)
    if (list) list.push(row)
    else pending.set(key, [row])
  }

  for (const e of events) {
    if (e.name === 'node_start') {
      group = null
      lanes = new Map()
      rows.push({ kind: 'node', node: e.node, timestamp: e.timestamp })
    } else if (e.name === 'fanout') {
      group = { kind: 'fanout', budget: e.budget, lanes: [], merged: null }
      lanes = new Map()
      rows.push(group)
    } else if (e.name === 'subagent_start') {
      if (!group) continue
      const lane: Lane = { agent: e.agent, question: e.question, rows: [], done: null }
      lanes.set(e.agent, lane)
      // Ordered by agent name, not arrival: the workers start concurrently and
      // whichever registers first is a race, but agent-1 is always the first
      // sub-question.
      group.lanes = [...group.lanes, lane].sort((a, b) => a.agent.localeCompare(b.agent))
    } else if (e.name === 'subagent_done') {
      const lane = lanes.get(e.agent)
      if (lane) lane.done = e
    } else if (e.name === 'merged') {
      if (group) group.merged = e
    } else if (e.name === 'tool_call') {
      const row: Extract<InnerRow, { kind: 'tool' }> = { kind: 'tool', call: e, result: null }
      push(row, e.agent)
      queue(row, e.agent)
    } else if (e.name === 'tool_result') {
      const list = pending.get(`${e.agent ?? ''}|${e.tool}`)
      const row = list?.find((r) => !r.result)
      if (row) row.result = e
    } else if (e.name === 'code_run') {
      rows.push({ kind: 'code', event: e })
    } else if (e.name === 'chart_ready') {
      rows.push({ kind: 'chart', event: e })
    } else if (e.name === 'results_filtered') {
      push({ kind: 'filtered', event: e }, e.agent)
    } else if (e.name === 'tool_skipped') {
      push({ kind: 'skipped', event: e }, e.agent)
    } else if (e.name === 'gate') {
      rows.push({ kind: 'gate', gate: e })
    } else if (e.name === 'error') {
      rows.push({ kind: 'error', message: e.message })
    }
  }
  return rows
}

// Rendered both at the top level and inside an agent's lane.
function InnerRowView({ row }: { row: InnerRow }) {
  if (row.kind === 'skipped') {
    const v = Object.values(row.event.input ?? {})[0] ?? ''
    return (
      <div className="trace-skipped">
        ⤾ skipped duplicate {row.event.tool} — {String(v).slice(0, 60)}
      </div>
    )
  }
  if (row.kind === 'filtered') {
    const f = row.event
    return (
      <div className="trace-skipped">
        ⊘ dropped {f.dropped} result{f.dropped === 1 ? '' : 's'} matching
        your excluded terms ({f.terms.join(', ')})
      </div>
    )
  }
  return <ToolCallCard call={row.call} result={row.result} />
}

// One sub-agent's own trace: its sub-question, then only its own tool calls.
function AgentLane({ lane, index }: { lane: Lane; index: number }) {
  const done = lane.done
  return (
    <div className={`lane${done ? ' lane-done' : ''}`}>
      <div className="lane-head">
        <span className="lane-badge">{index + 1}</span>
        <span className="lane-name">{lane.agent}</span>
        {done
          ? <span className="lane-status">✓ {done.findings} finding{done.findings === 1 ? '' : 's'}</span>
          : <span className="lane-status"><span className="spinner" /></span>}
      </div>
      <p className="lane-question">{lane.question}</p>
      <div className="lane-rows">
        {lane.rows.map((r, i) => <InnerRowView key={i} row={r} />)}
        {!lane.rows.length && !done && <p className="muted">Starting…</p>}
      </div>
    </div>
  )
}

export default function AgentTrace({ events, status }: { events: AgentEvent[]; status: AgentStatus }) {
  const endRef = useRef<HTMLDivElement>(null)

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
        if (row.kind === 'fanout') {
          return (
            <div key={i} className="fanout">
              <div className="fanout-head">
                ⑂ {row.lanes.length} agent{row.lanes.length === 1 ? '' : 's'} researching in
                parallel — {row.budget} shared tool call{row.budget === 1 ? '' : 's'}
              </div>
              <div className="lanes">
                {row.lanes.map((lane, li) => (
                  <AgentLane key={lane.agent} lane={lane} index={li} />
                ))}
              </div>
              {row.merged && (
                <div className="fanout-merged">
                  ⇥ merged {row.merged.agents} agent{row.merged.agents === 1 ? '' : 's'} —
                  {' '}{row.merged.findings} finding{row.merged.findings === 1 ? '' : 's'} after
                  removing duplicates
                </div>
              )}
            </div>
          )
        }
        if (row.kind === 'code') {
          return <CodeRunCard key={i} event={row.event} />
        }
        if (row.kind === 'chart') {
          return (
            <div key={i} className="trace-chart">
              📊 chart {row.event.index}: {row.event.title || 'untitled'}
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
        return <InnerRowView key={i} row={row} />
      })}

      {status === 'running' && (
        <div className="trace-working"><span className="spinner" /> working…</div>
      )}
      <div ref={endRef} />
    </section>
  )
}
