import { useCallback, useEffect, useRef, useState } from 'react'

/** Fetch now and every `ms`; returns data, error and a manual refresh. */
export function usePoll<T>(fn: () => Promise<T>, ms = 5000, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const refresh = useCallback(async () => {
    try { setData(await fnRef.current()); setError(null) } catch (e) { setError((e as Error).message) }
  }, [])
  useEffect(() => {
    refresh()
    if (!ms) return
    const t = setInterval(refresh, ms)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, refresh, ...deps])
  return { data, error, refresh, setData }
}

export function timeAgo(iso: string) {
  const d = new Date(iso).getTime()
  const s = Math.round((Date.now() - d) / 1000)
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

export function clock(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}
