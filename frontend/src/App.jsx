import ResearchInput from './components/ResearchInput'
import AgentTrace from './components/AgentTrace'
import ConfidenceBar from './components/ConfidenceBar'
import ReportViewer from './components/ReportViewer'
import Starfield from './components/Starfield'
import { useAgentStream } from './hooks/useAgentStream'
import { useStarfield } from './hooks/useStarfield'

export default function App() {
  const { events, status, report, confidence, error, start, stop } = useAgentStream()
  const [stars, toggleStars] = useStarfield()

  return (
    <>
      <Starfield enabled={stars} />

      <div className="page">
        <header className="header">
          <div className="header-row">
            <h1>Research Agent</h1>
            <button
              type="button"
              className="ghost starfield-toggle"
              onClick={toggleStars}
              aria-pressed={stars}
              title={stars ? 'Turn off the animated background' : 'Turn on the animated background'}
            >
              {stars ? '✦ Stars on' : '✧ Stars off'}
            </button>
          </div>
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
    </>
  )
}
