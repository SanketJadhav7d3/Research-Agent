import { useCallback, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import ReportChart from './ReportChart'
import { toDataUri } from '../lib/charts'

// Charts are placed by markers the agent wrote at the start of a line.
// Splitting the prose around them is simpler and more predictable than a
// custom remark plugin.
//
// Anything following the marker on that line is consumed and discarded: asked
// for a bare marker, the model reliably writes "[chart:1] Margin Comparison"
// instead, and that caption is already rendered under the figure. Being strict
// here meant the marker fell through as literal text.
const CHART_LINE = /^[ \t]*\[chart:(\d+)\][^\n]*$/gm

function splitOnCharts(markdown) {
  const parts = markdown.split(CHART_LINE)
  // split() with one capture group alternates: text, number, text, number…
  return parts.map((part, i) =>
    i % 2 === 0
      // A marker the agent invented with no chart behind it would otherwise
      // show up as literal text in the prose.
      ? { kind: 'markdown', text: part.replace(/\[chart:\d+\]/g, '') }
      : { kind: 'chart', index: Number(part) },
  )
}

// The agent appends its own Sources section to the markdown so that a copied or
// exported report is self-contained. On screen we render that list ourselves as
// a linked panel, so strip it from the prose to avoid showing it twice.
function splitReport(markdown) {
  const idx = markdown.indexOf('## Sources')
  return idx === -1 ? markdown : markdown.slice(0, idx).trimEnd()
}

// Turn bare [1] markers into links to the matching source. The negative
// lookahead leaves real markdown links like [text](url) alone.
function linkCitations(markdown) {
  return markdown.replace(/\[(\d+)\](?!\()/g, '[$1](#cite-$1)')
}

// A research run routinely gathers twenty or more sources, which pushes the
// report itself off the screen. Show enough to be useful, hide the tail.
const COLLAPSED_SOURCES = 6

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export default function ReportViewer({ report }) {
  const [copied, setCopied] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [active, setActive] = useState(null)
  const [showAll, setShowAll] = useState(false)

  const segments = useMemo(
    () => (report ? splitOnCharts(linkCitations(splitReport(report.report))) : []),
    [report],
  )

  const jumpToSource = useCallback((n) => {
    setActive(n)
    // A citation can point at a source the collapsed list is hiding, in which
    // case there is no element to scroll to. Expand first, then jump on the
    // next frame once the entry actually exists.
    if (n > COLLAPSED_SOURCES) setShowAll(true)
    requestAnimationFrame(() => {
      document
        .getElementById(`cite-${n}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
    // Clear the highlight so a later jump to the same source still registers.
    setTimeout(() => setActive((cur) => (cur === n ? null : cur)), 2200)
  }, [])

  if (!report) return null

  const citations = report.citations ?? []
  const charts = report.charts ?? []
  const visibleCitations = showAll ? citations : citations.slice(0, COLLAPSED_SOURCES)
  const hidden = citations.length - visibleCitations.length
  const words = report.report.split(/\s+/).length

  const copy = async () => {
    await navigator.clipboard.writeText(report.report)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const download = async () => {
    let markdown = report.report

    // An interactive chart cannot survive a markdown file, so each marker
    // becomes an embedded still of what the reader saw. Rendered from the spec
    // rather than from the page, so it works whether or not the chart is
    // currently on screen.
    if (charts.length) {
      setExporting(true)
      try {
        const images = await Promise.all(charts.map((c) => toDataUri(c).catch(() => null)))
        markdown = markdown.replace(/^[ \t]*\[chart:(\d+)\][ \t]*$/gm, (marker, n) => {
          const uri = images[Number(n) - 1]
          const title = charts[Number(n) - 1]?.title || `Figure ${n}`
          return uri ? `![${title}](${uri})` : marker
        })
      } finally {
        setExporting(false)
      }
    }

    const blob = new Blob([markdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'research-report.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  const components = {
    // Citation markers render as superscript chips that jump to the source.
    a({ href, children, ...props }) {
      if (href?.startsWith('#cite-')) {
        const n = Number(href.slice(6))
        const source = citations[n - 1]
        // Clicking opens the source itself. Shift-click (or no URL) falls back
        // to highlighting the entry in the Sources panel instead.
        return (
          <a
            className="cite-ref"
            href={source?.url || `#cite-${n}`}
            target={source?.url ? '_blank' : undefined}
            rel="noreferrer"
            title={source ? `${source.title}
${source.url}` : `Source ${n}`}
            onClick={(e) => {
              if (!source?.url || e.shiftKey) {
                e.preventDefault()
                jumpToSource(n)
              }
            }}
          >
            {n}
          </a>
        )
      }
      return (
        <a href={href} target="_blank" rel="noreferrer" {...props}>
          {children}
        </a>
      )
    },
  }

  return (
    <section className="report">
      <div className="report-head">
        <h2 className="section-title">Report</h2>
        <div className="report-meta">
          <span>
            {words.toLocaleString()} words · {citations.length} sources ·{' '}
            {report.total_tool_calls} tool calls
            {report.loops > 1 && ` · ${report.loops} rounds`}
          </span>
          <button className="ghost" onClick={copy}>
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button className="ghost" onClick={download} disabled={exporting}>
            {exporting ? 'Rendering…' : 'Download'}
          </button>
        </div>
      </div>

      <div className="markdown">
        {segments.map((segment, i) =>
          segment.kind === 'chart' ? (
            <ReportChart
              key={i}
              chart={charts[segment.index - 1]}
              index={segment.index}
            />
          ) : segment.text.trim() ? (
            <ReactMarkdown key={i} remarkPlugins={[remarkGfm]} components={components}>
              {segment.text}
            </ReactMarkdown>
          ) : null,
        )}
      </div>

      {citations.length > 0 && (
        <>
          <div className="sources-head">
            <h3 className="section-title sources-title">
              Sources <span className="sources-count">{citations.length}</span>
            </h3>
            {citations.length > COLLAPSED_SOURCES && (
              <button className="ghost" onClick={() => setShowAll((v) => !v)}>
                {showAll
                  ? 'Show fewer'
                  : `Show all ${citations.length}`}
              </button>
            )}
          </div>
          <ol className="citations">
            {visibleCitations.map((c, i) => (
              <li
                key={i}
                id={`cite-${i + 1}`}
                className={active === i + 1 ? 'citation active' : 'citation'}
              >
                <span className="cite-num">{i + 1}</span>
                <span className="cite-body">
                  <a href={c.url} target="_blank" rel="noreferrer">
                    {c.title || c.url}
                  </a>
                  <span className="cite-host">{hostOf(c.url)}</span>
                </span>
              </li>
            ))}
          </ol>
          {!showAll && hidden > 0 && (
            <button className="sources-more" onClick={() => setShowAll(true)}>
              {hidden} more source{hidden === 1 ? '' : 's'}
            </button>
          )}
        </>
      )}
    </section>
  )
}
