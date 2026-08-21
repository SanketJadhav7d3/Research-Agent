import { useEffect, useRef } from 'react'

// Stars are stored in polar coordinates around the centre of the viewport, so
// rotating the field is a matter of advancing one angle per star rather than
// running a matrix over every point.
//
// Depth does three things at once — nearer stars are bigger, brighter and
// sweep faster — which is what makes a flat rotation read as a field with
// volume rather than a spinning decal.
const DENSITY = 1 / 9000   // stars per square pixel
const MAX_STARS = 320
const BASE_SPEED = 0.000045 // radians per millisecond, at full depth

const TWINKLE_SPEED = 0.0012

function createStars(width, height) {
  // The field has to cover the corners even while rotating, so its radius is
  // the diagonal, not the width.
  const maxRadius = Math.hypot(width, height) / 2
  const count = Math.min(MAX_STARS, Math.round(width * height * DENSITY))

  return Array.from({ length: count }, () => {
    const depth = Math.random()
    return {
      // sqrt keeps the distribution even across the disc; without it stars
      // bunch up around the centre.
      radius: Math.sqrt(Math.random()) * maxRadius,
      angle: Math.random() * Math.PI * 2,
      depth,
      size: 0.4 + depth * 1.3,
      alpha: 0.18 + depth * 0.5,
      // Phase offset so they do not all pulse in unison.
      phase: Math.random() * Math.PI * 2,
      // A few stars pick up a faint colour cast; a field of pure white reads
      // as noise rather than sky.
      hue: Math.random() < 0.22
        ? (Math.random() < 0.5 ? '124, 140, 255' : '224, 177, 85')
        : '255, 255, 255',
    }
  })
}

export default function Starfield({ enabled }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    if (!enabled) return

    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')

    // Someone who has asked their OS for less motion gets the field without
    // the rotation, rather than nothing at all.
    const stillness = window.matchMedia('(prefers-reduced-motion: reduce)')
    let stars = []
    let width = 0
    let height = 0
    let frame = null
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

    const draw = (now) => {
      const elapsed = last === null ? 0 : Math.min(now - last, 100)
      last = now

      const cx = width / 2
      const cy = height / 2
      ctx.clearRect(0, 0, width, height)

      for (const star of stars) {
        if (!stillness.matches) {
          star.angle += BASE_SPEED * (0.25 + star.depth) * elapsed
        }
        const x = cx + Math.cos(star.angle) * star.radius
        const y = cy + Math.sin(star.angle) * star.radius

        // Skip the arithmetic for stars swung outside the viewport.
        if (x < -4 || x > width + 4 || y < -4 || y > height + 4) continue

        const twinkle = 0.75 + 0.25 * Math.sin(now * TWINKLE_SPEED + star.phase)
        ctx.fillStyle = `rgba(${star.hue}, ${star.alpha * twinkle})`
        ctx.beginPath()
        ctx.arc(x, y, star.size, 0, Math.PI * 2)
        ctx.fill()
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
