import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup, configure } from '@testing-library/react'

// Twenty-one jsdom files run in parallel on one laptop; recharts alone takes hundreds of
// milliseconds to lay out. The 1 s default makes a genuinely-passing assertion flaky under
// load, which teaches everyone to re-run the suite instead of reading it.
configure({ asyncUtilTimeout: 5000 })
import { resetSnapshotCache } from '../domain/snapshot'

afterEach(() => {
  cleanup()
  // The snapshot loader memoises its fetch for the life of the page, which is right in a
  // browser and wrong between tests: the second test would read the first test's fixture.
  resetSnapshotCache()
  // Cookies leak between tests otherwise: document.cookie has no clear().
  for (const part of document.cookie.split(';')) {
    const name = part.split('=')[0].trim()
    if (name) document.cookie = `${name}=; Max-Age=0; path=/`
  }
})

// jsdom implements none of these, and the app (or recharts) uses all three.
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  })
}
// jsdom defines scrollTo but throws "Not implemented" from it.
window.scrollTo = vi.fn()
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  window.ResizeObserver = globalThis.ResizeObserver
}
