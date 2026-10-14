import { useCallback, useEffect, useState } from 'react'
import { api } from '../services/api'

export function useBackendStatus() {
  const [online, setOnline] = useState(true)
  const [checking, setChecking] = useState(false)

  const check = useCallback(async () => {
    setChecking(true)
    try {
      const health = await api.health()
      setOnline(health.api === 'up' && health.database === 'up')
    } catch { setOnline(false) } finally { setChecking(false) }
  }, [])

  useEffect(() => {
    check()
    const id = setInterval(check, 20000)
    return () => clearInterval(id)
  }, [check])

  return { online, checking, check }
}
