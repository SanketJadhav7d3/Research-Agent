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
          Pose a question for investigation. The agent draws up a plan, selects
          its own instruments, searches and reads its sources, appraises the
          quality of its own findings — and sets down a report in which every
          claim is referred to the authority it came from.
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
