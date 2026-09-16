// One hook for "fetch something, and have all five states be real".
//
// Every screen in this app has to show loading, empty, error, denied and content, and the
// only way that happens consistently is if there is one place that produces them. A
// component calls `useAsync`, gets `{data, meta, error, loading, reload}`, and renders the
// shared state components — it never manages its own AbortController or race conditions.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

/**
 * @param {(opts:{signal:AbortSignal}) => Promise<any>} loader
 * @param {Array} deps            re-runs when these change
 * @param {object} [options]
 * @param {boolean} [options.enabled=true]  skip the call entirely (role gates, missing id)
 * @param {*} [options.initialData]
 */
export function useAsync(loader, deps = [], { enabled = true, initialData = null } = {}) {
  const [state, setState] = useState(() => ({
    data: initialData, meta: null, source: null, error: null, loading: enabled,
  }))
  const [nonce, setNonce] = useState(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  useEffect(() => {
    if (!enabled) {
      setState({ data: initialData, meta: null, source: null, error: null, loading: false })
      return undefined
    }
    const controller = new AbortController()
    let live = true
    setState((prev) => ({ ...prev, loading: true, error: null }))
    Promise.resolve()
      .then(() => loaderRef.current({ signal: controller.signal }))
      .then((result) => {
        if (!live) return
        // A loader may return the envelope or just the payload; accept both.
        const isEnvelope = result && typeof result === 'object' && 'data' in result && !Array.isArray(result)
        setState({
          data: isEnvelope ? result.data : result,
          meta: isEnvelope ? result.meta ?? null : null,
          source: isEnvelope ? result.source ?? null : null,
          error: null,
          loading: false,
        })
      })
      .catch((error) => {
        if (!live || error?.name === 'AbortError') return
        setState({ data: null, meta: null, source: null, error, loading: false })
      })
    return () => { live = false; controller.abort() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  return useMemo(() => ({ ...state, reload }), [state, reload])
}

export default useAsync
