import { useState } from 'react'

const MARKS = {
  web_search: '🔍',
  news_search: '📰',
  read_page: '📄',
  read_pdf: '📕',
  market_data: '📈',
}

// One tool call plus its result, collapsed by default.
export default function ToolCallCard({ call, result }) {
  const [open, setOpen] = useState(false)
  const query = Object.values(call.input ?? {})[0] ?? ''

  return (
    <div className="tool-card">
      <button className="tool-head" onClick={() => setOpen((o) => !o)}>
        <span className="tool-icon">{MARKS[call.tool] ?? '🔧'}</span>
        <span className="tool-name">{call.tool}</span>
        <span className="tool-query">{query}</span>
        <span className="tool-count">
          {result ? `${result.result_count} results` : '…'}
        </span>
        <span className="tool-chevron">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="tool-body">
          {result?.sources?.length ? (
            <ul className="sources">
              {result.sources.map((s, i) => (
                <li key={i}>
                  <a href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Waiting for results…</p>
          )}
        </div>
      )}
    </div>
  )
}
