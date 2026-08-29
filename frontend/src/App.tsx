import Starfield from './components/Starfield'
import Home from './pages/Home'
import Research from './pages/Research'
import { useAgentStream } from './hooks/useAgentStream'
import { useRoute } from './hooks/useRoute'
import { useStarfield } from './hooks/useStarfield'

export default function App() {
  const agent = useAgentStream()
  const [stars, toggleStars] = useStarfield()
  const [route, navigate] = useRoute()

  const onApp = route === '/app'

  return (
    <>
      {/* Mounted above the route switch on purpose. Rendering it inside a page
          would unmount and rebuild it on every navigation, resetting the
          rotation to zero and replaying the fade-in — the background has to be
          the one thing that does not change between pages. */}
      <Starfield enabled={stars} />

      <nav className="topbar">
        <button type="button" className="brand" onClick={() => navigate('/')}>
          ✦ Research Agent
        </button>

        <div className="topbar-right">
          {onApp ? (
            <button type="button" className="ghost" onClick={() => navigate('/')}>
              Home
            </button>
          ) : (
            <button type="button" className="ghost" onClick={() => navigate('/app')}>
              Open the app
            </button>
          )}

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
      </nav>

      {onApp ? <Research {...agent} /> : <Home navigate={navigate} />}
    </>
  )
}
