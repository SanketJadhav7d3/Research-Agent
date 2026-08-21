import ResearchInput from './components/ResearchInput'
import AgentTrace from './components/AgentTrace'
import ConfidenceBar from './components/ConfidenceBar'
import ReportViewer from './components/ReportViewer'
import { useAgentStream } from './hooks/useAgentStream'

export default function App() {
  const { events, status, report, confidence, error, start, stop } = useAgentStream()

  return (
    <div className="page">
      <header className="header">
        <h1>Research Agent</h1>
        <p>
          Ask a research question. The agent plans its approach, picks its own
          tools, searches and reads sources, judges how well it did, and writes
          a report where every claim links back to where it came from.
        </p>
      </header>

      <ResearchInput onStart={start} onStop={stop} status={status} />

      {error && <div className="banner error">⚠ {error}</div>}

      <ConfidenceBar history={confidence} />
      <AgentTrace events={events} status={status} />
      <ReportViewer report={report} />
    </div>
  )
}
