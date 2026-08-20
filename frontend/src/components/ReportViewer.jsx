import { useState } from 'react'
import ReactMarkdown from 'react-markdown'

export default function ReportViewer({ report }) {
  const [copied, setCopied] = useState(false)
  if (!report) return null

  const copy = async () => {
    await navigator.clipboard.writeText(report.report)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <section className="report">
      <div className="report-head">
        <h2 className="section-title">Report</h2>
        <div className="report-meta">
          {report.total_tool_calls} tool calls · {report.citations?.length ?? 0} sources
          <button className="ghost" onClick={copy}>
            {copied ? 'Copied' : 'Copy markdown'}
          </button>
        </div>
      </div>
      <div className="markdown">
        <ReactMarkdown>{report.report}</ReactMarkdown>
      </div>
    </section>
  )
}
