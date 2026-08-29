import { useCallback, useRef, useState } from 'react'
import { streamResearch } from '../lib/api'
import type { AgentEvent, AgentStatus, ConfidenceEntry, ReportData } from '../types'

export interface StartArgs {
  goal: string
  provider?: string
  model?: string
  apiKey?: string
  includeKeywords?: string[]
  excludeKeywords?: string[]
}

// Drives one research run and accumulates its trace.
export function useAgentStream() {
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [status, setStatus] = useState<AgentStatus>('idle')
  const [report, setReport] = useState<ReportData | null>(null)
  const [confidence, setConfidence] = useState<ConfidenceEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const start = useCallback(async ({
    goal, provider, model, apiKey, includeKeywords, excludeKeywords,
  }: StartArgs) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setEvents([])
    setReport(null)
    setConfidence([])
    setError(null)
    setStatus('running')

    try {
      await streamResearch(
        {
          goal,
          ...(provider ? { provider } : {}),
          ...(model ? { model } : {}),
          ...(apiKey ? { api_key: apiKey } : {}),
          ...(includeKeywords?.length ? { include_keywords: includeKeywords } : {}),
          ...(excludeKeywords?.length ? { exclude_keywords: excludeKeywords } : {}),
        },
        {
          signal: controller.signal,
          onEvent: (name, data) => {
            const event = { name, ...data } as AgentEvent
            setEvents((prev) => [...prev, event])
            if (name === 'confidence_check') setConfidence((prev) => [...prev, data as ConfidenceEntry])
            if (name === 'report_ready') setReport(data as unknown as ReportData)
            if (name === 'error') setError((data as { message: string }).message)
          },
        },
      )
      setStatus((s) => (s === 'running' ? 'done' : s))
    } catch (err) {
      if (err instanceof Error && err.name !== 'AbortError') {
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
