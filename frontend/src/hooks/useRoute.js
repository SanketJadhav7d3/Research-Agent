import { useCallback, useEffect, useState } from 'react'

// Two pages is not worth a router dependency. This is the History API with a
// popstate listener, which is most of what a router does at this size.
//
// It relies on the server returning index.html for unknown paths — nginx
// already does that (`try_files $uri $uri/ /index.html`), and Vite's dev
// server does it by default. Without that, a hard refresh on /app would 404.

const normalise = (path) =>
  path.length > 1 && path.endsWith('/') ? path.slice(0, -1) : path

export function useRoute() {
  const [route, setRoute] = useState(() => normalise(window.location.pathname))

  useEffect(() => {
    const onPop = () => setRoute(normalise(window.location.pathname))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = useCallback((to) => {
    if (normalise(to) === normalise(window.location.pathname)) return
    window.history.pushState(null, '', to)
    setRoute(normalise(to))
    // Browsers restore scroll on back/forward but not on pushState, so a
    // navigation would otherwise land halfway down the new page.
    window.scrollTo(0, 0)
  }, [])

  return [route, navigate]
}
