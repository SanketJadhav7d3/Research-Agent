import { useCallback, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

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

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export default function ReportViewer({ report }) {
  const [copied, setCopied] = useState(false)
  const [active, setActive] = useState(null)

  const prose = useMemo(
    () => (report ? linkCitations(splitReport(report.report)) : ''),
    [report],
  )

  const jumpToSource = useCallback((n) => {
    setActive(n)
    document
      .getElementById(`cite-${n}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    // Clear the highlight so a later jump to the same source still registers.
    setTimeout(() => setActive((cur) => (cur === n ? null : cur)), 2200)
  }, [])

  if (!report) return null

  const citations = report.citations ?? []
  const words = report.report.split(/\s+/).length

  const copy = async () => {
    await navigator.clipboard.writeText(report.report)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const download = () => {
    const blob = new Blob([report.report], { type: 'text/markdown' })
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
          <button className="ghost" onClick={download}>
            Download
          </button>
        </div>
      </div>

      <div className="markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {prose}
        </ReactMarkdown>
      </div>

      {citations.length > 0 && (
        <>
          <h3 className="section-title sources-title">Sources</h3>
          <ol className="citations">
            {citations.map((c, i) => (
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
        </>
      )}
    </section>
  )
}
