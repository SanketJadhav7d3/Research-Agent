import { useEffect, useRef } from 'react'

/* Rotating starfield with occasional shooting stars.
 *
 * Stars live in polar coordinates around the centre of the viewport, so
 * rotating the field means adding one shared angle rather than transforming
 * every point.
 *
 * The rotation is rigid — every star advances by the same angle regardless of
 * its distance. Giving each star its own speed (as most versions of this
 * effect do) is parallax: the field shears, and it reads as drifting rather
 * than as one structure turning.
 *
 * Two details do most of the work in making the motion legible:
 *
 *   The field extends to the full diagonal, not half of it. Stars therefore
 *   swing in and out of the viewport instead of all staying on screen, and
 *   arriving stars are a far stronger motion cue than one sliding across.
 *
 *   Flicker is deep (0.45 to 1.0), not a gentle pulse. It is the flicker that
 *   registers first, and it is what makes the field feel alive rather than
 *   printed.
 */

// Stars per square pixel *of visible viewport*, which is the only figure that
// describes what you actually see. Counting the whole field instead is
// misleading: it spans the full diagonal, so on a 1920x1080 window barely a
// seventh of it is on screen at any moment, and a total that sounds generous
// renders as a thin scattering.
const VISIBLE_DENSITY = 1 / 6200
const MAX_STARS = 3200

// Radians per millisecond. One full revolution takes about 2.5 minutes.
const ROTATION_SPEED = (Math.PI * 2) / 150_000

const FLICKER_SPEED = 0.0015

// Shooting stars: one at a time, gone in under a second, and roughly one
// every seven seconds. Frequent enough to catch while reading a report,
// infrequent enough that it never becomes the thing you are watching.
const SHOOTING_CHANCE_PER_SECOND = 0.15
const SHOOTING_SPEED = 0.55        // px per millisecond
const SHOOTING_TRAIL = 120         // px

function createStars(width, height) {
  // Full diagonal, so the field runs past the edges of the viewport and stars
  // rotate into view rather than merely across it.
  const maxRadius = Math.hypot(width, height)
  // Scale the total by how much larger the field is than the window, so the
  // on-screen density comes out at VISIBLE_DENSITY regardless of window shape.
  const spread = (Math.PI * maxRadius * maxRadius) / (width * height)
  const count = Math.min(
    MAX_STARS,
    Math.round(width * height * VISIBLE_DENSITY * spread),
  )

  return Array.from({ length: count }, () => {
    const depth = Math.random()
    return {
      // sqrt keeps the distribution even across the disc; without it stars
      // bunch up around the centre.
      radius: Math.sqrt(Math.random()) * maxRadius,
      angle: Math.random() * Math.PI * 2,
      size: 0.5 + depth * 1.2,
      alpha: 0.35 + depth * 0.5,
      // Phase offset so they do not all pulse in unison.
      phase: Math.random() * Math.PI * 2,
      // A few stars pick up a faint colour cast; a field of pure white reads
      // as noise rather than sky.
      hue: Math.random() < 0.22
        ? (Math.random() < 0.5 ? '150, 175, 255' : '232, 197, 131')
        : '255, 255, 255',
    }
  })
}

function spawnShootingStar(width, height) {
  // Enter from the top edge, travelling down and across. Either direction, so
  // it does not become a metronome.
  const leftToRight = Math.random() < 0.5
  const angle = (Math.random() * 0.35 + 0.15) * Math.PI // 27deg to 63deg
  return {
    x: leftToRight ? Math.random() * width * 0.5 : width - Math.random() * width * 0.5,
    y: Math.random() * height * 0.4,
    vx: Math.cos(angle) * SHOOTING_SPEED * (leftToRight ? 1 : -1),
    vy: Math.sin(angle) * SHOOTING_SPEED,
    life: 0,
    span: 700 + Math.random() * 500,  // ms
  }
}

export default function Starfield({ enabled }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    if (!enabled) return

    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')

    let stars = []
    let shooting = null
    let width = 0
    let height = 0
    let frame = null
    // Total rotation of the field, in radians. Accumulated rather than derived
    // from a start timestamp so that pausing on a hidden tab resumes from
    // where it stopped instead of jumping forward.
    let rotation = 0
    let last = null

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      width = window.innerWidth
      height = window.innerHeight
      canvas.width = width * dpr
      canvas.height = height * dpr
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      stars = createStars(width, height)
    }

    const drawShootingStar = () => {
      const { x, y, vx, vy, life, span } = shooting
      // Fade in over the first fifth of its life, out over the rest.
      const t = life / span
      const fade = t < 0.2 ? t / 0.2 : 1 - (t - 0.2) / 0.8

      const len = Math.hypot(vx, vy)
      const tailX = x - (vx / len) * SHOOTING_TRAIL
      const tailY = y - (vy / len) * SHOOTING_TRAIL

      const gradient = ctx.createLinearGradient(x, y, tailX, tailY)
      gradient.addColorStop(0, `rgba(255, 255, 255, ${0.85 * fade})`)
      gradient.addColorStop(0.35, `rgba(180, 200, 255, ${0.3 * fade})`)
      gradient.addColorStop(1, 'rgba(180, 200, 255, 0)')

      ctx.strokeStyle = gradient
      ctx.lineWidth = 1.6
      ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.lineTo(tailX, tailY)
      ctx.stroke()
    }

    const draw = (now) => {
      // Clamped so a stutter or a resumed tab cannot produce a lurch.
      const elapsed = last === null ? 0 : Math.min(now - last, 100)
      last = now

      const cx = width / 2
      const cy = height / 2
      ctx.clearRect(0, 0, width, height)

      // One angle for the entire field, advanced once per frame. This is what
      // makes it turn as a single body.
      rotation += ROTATION_SPEED * elapsed

      for (const star of stars) {
        const angle = star.angle + rotation
        const x = cx + Math.cos(angle) * star.radius
        const y = cy + Math.sin(angle) * star.radius

        // Skip the arithmetic for stars swung outside the viewport.
        if (x < -4 || x > width + 4 || y < -4 || y > height + 4) continue

        const flicker = 0.45 + Math.abs(Math.sin(now * FLICKER_SPEED + star.phase)) * 0.55
        ctx.fillStyle = `rgba(${star.hue}, ${star.alpha * flicker})`
        ctx.beginPath()
        ctx.arc(x, y, star.size, 0, Math.PI * 2)
        ctx.fill()
      }

      if (shooting) {
        shooting.x += shooting.vx * elapsed
        shooting.y += shooting.vy * elapsed
        shooting.life += elapsed
        if (shooting.life >= shooting.span) shooting = null
        else drawShootingStar()
      } else if (Math.random() < (SHOOTING_CHANCE_PER_SECOND * elapsed) / 1000) {
        shooting = spawnShootingStar(width, height)
      }

      frame = requestAnimationFrame(draw)
    }

    // A background animation has no business burning frames on a tab nobody is
    // looking at.
    const visibility = () => {
      if (document.hidden) {
        cancelAnimationFrame(frame)
        frame = null
      } else if (frame === null) {
        last = null
        frame = requestAnimationFrame(draw)
      }
    }

    resize()
    frame = requestAnimationFrame(draw)
    window.addEventListener('resize', resize)
    document.addEventListener('visibilitychange', visibility)

    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', resize)
      document.removeEventListener('visibilitychange', visibility)
    }
  }, [enabled])

  if (!enabled) return null
  return <canvas ref={canvasRef} className="starfield" aria-hidden="true" />
}
