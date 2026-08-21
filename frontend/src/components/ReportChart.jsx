import { useEffect, useRef, useState } from 'react'
import { PLOT_CONFIG, loadPlotly, themed } from '../lib/charts'

// One chart in the report. Plotly figures are interactive — hover for values,
// drag to zoom, double-click to reset. Matplotlib figures arrive as images and
// are shown as-is.
export default function ReportChart({ chart, index }) {
  const holder = useRef(null)
  const [failed, setFailed] = useState(null)

  useEffect(() => {
    if (!chart || chart.format !== 'plotly') return
    let cancelled = false
    let node = null

    loadPlotly()
      .then((Plotly) => {
        if (cancelled || !holder.current) return
        node = holder.current
        const { data, layout } = themed(chart.spec)
        return Plotly.newPlot(node, data, layout, PLOT_CONFIG)
      })
      .catch((err) => {
        if (!cancelled) setFailed(err.message)
      })

    return () => {
      cancelled = true
      // Plotly attaches resize listeners to the window; without purge they
      // outlive the component and fire against a detached node.
      if (node) loadPlotly().then((Plotly) => Plotly.purge(node)).catch(() => {})
    }
  }, [chart])

  if (!chart) return null

  return (
    <figure className="chart" id={`chart-${index}`}>
      {chart.format === 'png' ? (
        <img src={`data:image/png;base64,${chart.data}`} alt={chart.title || 'Chart'} />
      ) : failed ? (
        <p className="muted">This chart could not be rendered — {failed}</p>
      ) : (
        <div className="chart-plot" ref={holder} />
      )}
      {chart.title && (
        <figcaption>
          <span className="chart-num">Figure {index}</span>
          {chart.title}
        </figcaption>
      )}
    </figure>
  )
}
