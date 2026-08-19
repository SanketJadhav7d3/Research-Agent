import { useEffect, useState } from 'react'

const STYLES = {
  page: {
    minHeight: '100vh',
    display: 'grid',
    placeItems: 'center',
    fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    background: '#0f1117',
    color: '#e6e8ee',
  },
  card: { textAlign: 'center', lineHeight: 1.6 },
  dot: (color) => ({
    display: 'inline-block',
    width: 10,
    height: 10,
    borderRadius: '50%',
    background: color,
    marginRight: 8,
  }),
}

const STATUS_COLOR = { checking: '#d9a441', ok: '#3fb950', error: '#f85149' }

export default function App() {
  const [status, setStatus] = useState('checking')
  const [detail, setDetail] = useState('contacting backend…')

  useEffect(() => {
    fetch('/api/health')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data) => {
        setStatus('ok')
        setDetail(`backend responded: ${JSON.stringify(data)}`)
      })
      .catch((err) => {
        setStatus('error')
        setDetail(`backend unreachable — ${err.message}`)
      })
  }, [])

  return (
    <div style={STYLES.page}>
      <div style={STYLES.card}>
        <h1>Research Agent</h1>
        <p style={{ opacity: 0.7 }}>Sprint 1 — scaffold</p>
        <p>
          <span style={STYLES.dot(STATUS_COLOR[status])} />
          {detail}
        </p>
      </div>
    </div>
  )
}
