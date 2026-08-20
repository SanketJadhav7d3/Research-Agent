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
          Give it a question. It plans, chooses its own tools, searches, judges
          how well it did, and writes a cited report.
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
