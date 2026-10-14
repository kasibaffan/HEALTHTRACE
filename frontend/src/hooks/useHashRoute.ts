import { useEffect, useState } from 'react'

export interface Route { page: 'dashboard' | 'cases' | 'case' | 'evidence' | 'policies' | 'audit'; caseId?: string }

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  switch (parts[0]) {
    case 'cases': return parts[1] ? { page: 'case', caseId: parts[1] } : { page: 'cases' }
    case 'evidence': return { page: 'evidence' }
    case 'policies': return { page: 'policies' }
    case 'audit': return { page: 'audit' }
    default: return { page: 'dashboard' }
  }
}

export function navigate(path: string) {
  window.location.hash = path
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
