// Backend client. All calls go to /api, which nginx proxies to the backend, so
// the browser only ever talks to one origin and no CORS preflight is involved.

const BASE = '/api'

export async function fetchProviders() {
  const res = await fetch(`${BASE}/providers`)
  if (!res.ok) throw new Error(`providers: HTTP ${res.status}`)
  return res.json()
}

// Streams the agent trace. POST rather than EventSource so the user's own API
// key travels in the request body, never in a URL where logs would capture it.
export async function streamResearch(body, { onEvent, signal }) {
  const res = await fetch(`${BASE}/research`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}${detail ? ` — ${detail.slice(0, 200)}` : ''}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // SSE frames are separated by a blank line. Keep the trailing partial
    // frame in the buffer until the rest of it arrives.
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      if (!frame.trim()) continue
      let name = 'message'
      const dataLines = []
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) name = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (!dataLines.length) continue
      try {
        onEvent(name, JSON.parse(dataLines.join('\n')))
      } catch {
        // A malformed frame should not kill the stream.
      }
    }
  }
}
