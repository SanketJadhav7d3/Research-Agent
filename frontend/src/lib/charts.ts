// Chart helpers shared by the renderer and the markdown export.
//
// Plotly is loaded on demand. It is by far the largest dependency here, and
// most reports contain no chart at all, so nobody pays for it until a chart
// actually arrives.

import type { Chart, PlotlySpec } from '../types'

// plotly.js-dist-min ships no types; this covers only what this app calls.
interface PlotlyModule {
  newPlot(node: HTMLElement, data: unknown[], layout: Record<string, unknown>, config: Record<string, unknown>): Promise<unknown>
  purge(node: HTMLElement): void
  toImage(spec: { data: unknown[]; layout: Record<string, unknown> }, opts: Record<string, unknown>): Promise<string>
}

let plotlyPromise: Promise<PlotlyModule> | null = null

export function loadPlotly(): Promise<PlotlyModule> {
  if (!plotlyPromise) {
    plotlyPromise = import('plotly.js-dist-min').then((m: any) => m.default ?? m)
  }
  return plotlyPromise
}

// The spec was produced by code an LLM wrote after reading arbitrary web
// pages, so it is untrusted input. Plotly renders a subset of HTML in titles,
// labels and hover templates, which makes that a script-injection route.
// Stripping anything tag-shaped from every string closes it without breaking
// legitimate labels.
function scrub<T>(value: T): T {
  if (typeof value === 'string') return value.replace(/<[^>]*>/g, '') as unknown as T
  if (Array.isArray(value)) return value.map(scrub) as unknown as T
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value)) out[k] = scrub(v)
    return out as unknown as T
  }
  return value
}

// Read a CSS custom property so the charts follow the app's theme rather than
// carrying colours of their own.
function token(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name)
  return value.trim() || fallback
}

// Applied on the client, not asked of the model. Prompting for a palette never
// matches exactly and costs a retry when it doesn't; overriding here means
// every chart fits whatever the theme is at the time.
export function themed(spec: PlotlySpec | undefined): { data: unknown[]; layout: Record<string, unknown> } {
  const safe = scrub(spec ?? {})
  const text = token('--text-dim', '#97a3bf')
  const grid = token('--border', '#1d283f')
  const axis = {
    gridcolor: grid,
    zerolinecolor: grid,
    linecolor: grid,
    tickfont: { color: text, size: 12 },
    title: { font: { color: text, size: 13 } },
  }

  const layout = (safe.layout ?? {}) as Record<string, unknown>

  return {
    data: safe.data ?? [],
    layout: {
      ...layout,
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'Inter, system-ui, sans-serif', color: text, size: 13 },
      colorway: [
        token('--accent', '#8ba3f5'),
        token('--green', '#5fc9a5'),
        token('--gold', '#e8c583'),
        token('--red', '#ef8fa2'),
        '#9b8bd6',
        '#6fb3c9',
      ],
      // The card already carries the chart's title, so drop Plotly's — two
      // titles stacked look like a mistake.
      title: undefined,
      margin: { l: 56, r: 20, t: 16, b: 48 },
      xaxis: { ...axis, ...(layout.xaxis as Record<string, unknown> | undefined) },
      yaxis: { ...axis, ...(layout.yaxis as Record<string, unknown> | undefined) },
      legend: { font: { color: text, size: 12 }, orientation: 'h', y: -0.22 },
      hoverlabel: {
        bgcolor: token('--surface-2', '#1a2438'),
        bordercolor: token('--border-strong', '#2c3a57'),
        font: { color: token('--text', '#e3e9f7'), family: 'Inter, sans-serif' },
      },
    },
  }
}

export const PLOT_CONFIG = {
  responsive: true,
  displaylogo: false,
  // The full toolbar is mostly noise for a reader; keep zoom, pan and reset.
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d', 'toImage'],
}

// Renders a chart to a PNG data URI without needing it on screen. Used by the
// markdown export, where interactive charts obviously cannot survive.
export async function toDataUri(chart: Chart): Promise<string> {
  if (chart.format === 'png') return `data:image/png;base64,${chart.data}`
  const Plotly = await loadPlotly()
  return Plotly.toImage(themed(chart.spec), {
    format: 'png', width: 900, height: 500,
  })
}
