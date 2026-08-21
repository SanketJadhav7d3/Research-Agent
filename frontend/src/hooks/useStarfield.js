import { useEffect, useState } from 'react'

const KEY = 'starfield'

// On by default, except for someone whose OS asks for reduced motion — they
// get it off, and can switch it on if they want it.
//
// The effect used to honour that preference by freezing the rotation while
// still drawing the field, which is worse than either option: anyone with
// Windows' animation effects switched off saw a starfield that simply never
// moved, with no indication why. An explicit toggle is the better answer —
// the OS preference picks the default, the user's own choice overrides it.
function initial() {
  try {
    const stored = window.localStorage.getItem(KEY)
    if (stored) return stored === 'on'
    return !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    // Private mode and some embedded browsers throw on access.
    return true
  }
}

export function useStarfield() {
  const [enabled, setEnabled] = useState(initial)

  useEffect(() => {
    try {
      window.localStorage.setItem(KEY, enabled ? 'on' : 'off')
    } catch {
      // Not being able to remember the choice is not worth breaking over.
    }
  }, [enabled])

  return [enabled, () => setEnabled((v) => !v)]
}
