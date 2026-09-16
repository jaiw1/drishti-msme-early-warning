// A sortable, keyboard-navigable table.
//
// Three a11y facts this encodes so no screen has to remember them:
//   * every header cell is a `<th scope="col">`, and a sortable one carries `aria-sort`
//     so a screen reader announces the current order rather than a bare column name;
//   * rows are a roving-tabindex group — one Tab stop for the whole table, then arrow
//     keys within it, so a keyboard user is not trapped in a hundred tab stops;
//   * a clickable row is a real activation target (Enter and Space), not a `div` with an
//     onClick that a keyboard cannot reach.
//
// The sort is a controlled prop, because the watch-list sorts server-side against the
// contract's allowlist and other tables sort in memory.

import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'

const ARIA_SORT = { asc: 'ascending', desc: 'descending' }

/**
 * A sortable column header.
 *
 * `direction` is fixed, not toggled: `GET /drishti/portfolio` takes a `sort` field and no
 * order, and it sorts descending. A header that offered to reverse the order would be
 * promising something the server will not do — so the button says "sort by this column"
 * and `aria-sort` reports the order that is actually in force.
 */
export function SortableHeader({ column, sort, onSort, align = 'left', title, children }) {
  const active = sort?.key === column
  const direction = sort?.direction || 'desc'
  const Icon = !active ? ArrowUpDown : direction === 'asc' ? ArrowUp : ArrowDown
  return (
    <th
      scope="col"
      aria-sort={active ? ARIA_SORT[direction] : 'none'}
      className={`px-3 py-2 font-semibold text-slate-600 ${align === 'right' ? 'text-right' : 'text-left'}`}
    >
      <button
        type="button"
        onClick={() => onSort?.({ key: column, direction })}
        title={title}
        className={`inline-flex items-center gap-1 rounded font-semibold transition hover:text-idbi-green focus:outline-none focus-visible:ring-2 focus-visible:ring-idbi-green ${align === 'right' ? 'flex-row-reverse' : ''}`}
      >
        {children}
        <Icon size={12} aria-hidden="true" className={active ? 'text-idbi-green' : 'opacity-50'} />
        <span className="sr-only">
          {active
            ? `, the column the list is sorted by, ${ARIA_SORT[direction]}.`
            : `, activate to sort the list by this column, ${ARIA_SORT[direction]}.`}
        </span>
      </button>
    </th>
  )
}

/**
 * Roving tabindex over the rows of one table body.
 * Returns the props each row needs; the caller spreads them onto the `<tr>`.
 */
export function useRovingRows(count, { onActivate } = {}) {
  const [active, setActive] = useState(0)
  const bodyRef = useRef(null)
  const shouldFocus = useRef(false)

  useEffect(() => { if (active > count - 1) setActive(Math.max(0, count - 1)) }, [count, active])

  useEffect(() => {
    if (!shouldFocus.current) return
    shouldFocus.current = false
    const rows = bodyRef.current?.querySelectorAll('tr[data-row]')
    rows?.[active]?.focus()
  }, [active])

  const move = useCallback((to) => {
    if (count === 0) return
    shouldFocus.current = true
    setActive(Math.max(0, Math.min(count - 1, to)))
  }, [count])

  const rowProps = useCallback((index, key) => ({
    'data-row': true,
    tabIndex: index === active ? 0 : -1,
    // The hook focuses a row itself when the arrow keys move the tab stop, and that
    // focus event lands back here. Bail out rather than re-setting the same index.
    onFocus: () => setActive((prev) => (prev === index ? prev : index)),
    onKeyDown: (event) => {
      switch (event.key) {
        case 'ArrowDown': event.preventDefault(); move(index + 1); break
        case 'ArrowUp': event.preventDefault(); move(index - 1); break
        case 'Home': event.preventDefault(); move(0); break
        case 'End': event.preventDefault(); move(count - 1); break
        case 'Enter':
        case ' ':
          if (onActivate) { event.preventDefault(); onActivate(key, index) }
          break
        default: break
      }
    },
  }), [active, count, move, onActivate])

  return { bodyRef, rowProps, active }
}

/**
 * The table chrome. `caption` is not decoration: it is what a screen-reader user hears
 * when they land on the table, and the only place the row count belongs.
 */
export default function DataTable({ caption, captionVisible = false, children, className = '', ...rest }) {
  return (
    <table className={`w-full text-sm ${className}`} {...rest}>
      <caption className={captionVisible ? 'px-3 py-2 text-left text-xs text-slate-600' : 'sr-only'}>
        {caption}
      </caption>
      {children}
    </table>
  )
}
