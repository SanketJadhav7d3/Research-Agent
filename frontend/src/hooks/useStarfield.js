import { useEffect, useState } from 'react'

const KEY = 'starfield'

// On by default. Only a stored "off" turns it off, so a first-time visitor
// always sees the effect and anyone who switched it off keeps that choice.
function initial() {
  try {
    return window.localStorage.getItem(KEY) !== 'off'
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
