import { useCallback, useRef, useState } from 'react'
import { streamResearch } from '../lib/api'

// Drives one research run and accumulates its trace.
// status: idle | running | done | error
export function useAgentStream() {
  const [events, setEvents] = useState([])
  const [status, setStatus] = useState('idle')
  const [report, setReport] = useState(null)
  const [confidence, setConfidence] = useState(null)
  const [error, setError] = useState(null)
  const abortRef = useRef(null)

  const start = useCallback(async ({ goal, provider, model, apiKey }) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setEvents([])
    setReport(null)
    setConfidence(null)
    setError(null)
    setStatus('running')

    try {
      await streamResearch(
        {
          goal,
          ...(provider ? { provider } : {}),
          ...(model ? { model } : {}),
          ...(apiKey ? { api_key: apiKey } : {}),
        },
        {
          signal: controller.signal,
          onEvent: (name, data) => {
            setEvents((prev) => [...prev, { name, ...data }])
            if (name === 'confidence_check') setConfidence(data)
            if (name === 'report_ready') setReport(data)
            if (name === 'error') setError(data.message)
          },
        },
      )
      setStatus((s) => (s === 'running' ? 'done' : s))
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message)
        setStatus('error')
      }
    }
  }, [])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    setStatus('idle')
  }, [])

  return { events, status, report, confidence, error, start, stop }
}
