export default function Home({ navigate }: { navigate: (to: string) => void }) {
  return (
    <main className="home">
      <h1 className="home-title">Research Agent</h1>

      <p className="home-lead">
        Ask a research question. It plans an approach, chooses its own tools,
        reads sources, writes and runs code to chart what it finds, judges how
        well it did, and produces a report where every claim links back to
        where it came from.
      </p>

      <div className="home-actions">
        <button type="button" onClick={() => navigate('/app')}>
          Try it
        </button>
        <a
          className="home-link"
          href="https://github.com/SanketJadhav7d3/Research-Agent"
          target="_blank"
          rel="noreferrer"
        >
          Source on GitHub ↗
        </a>
      </div>

      <figure className="home-demo">
        {/* Muted autoplay is permitted without a user gesture; controls stay so
            it can be paused, scrubbed or unmuted. playsInline stops iOS taking
            it fullscreen the moment it starts. */}
        <video
          src="/research-agent.mp4"
          controls
          autoPlay
          muted
          loop
          playsInline
          preload="metadata"
        >
          Your browser cannot play this video.{' '}
          <a href="/research-agent.mp4">Download it instead.</a>
        </video>
        <figcaption>A full run, from question to cited report.</figcaption>
      </figure>
    </main>
  )
}
