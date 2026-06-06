import { useMemo, useLayoutEffect, useRef, useState } from 'react'
import { AnsiText } from './AnsiText'
import { isAtBottom } from './scrollFollow'
import { tailLines, TAIL_MAX_LINES } from './tailLines'

// Shared playbook-log scroll pane (#373). Tail-follows new output while the user is
// pinned to the bottom; an upward scroll releases the lock so earlier tasks can be
// read without being yanked back; scrolling to the bottom (or the Jump button)
// re-arms following. Single source of truth for both PlaybookJobDetail and the
// run modal — no duplicated scroll logic.
//
// `following` is driven by real onScroll events, never recomputed after content is
// appended, so a large 3s polling burst can't accidentally cancel following.
export function LogPane({
  raw,
  isLive = false,
  emptyText = 'No output recorded',
  className = '',
}: {
  raw: string
  isLive?: boolean
  emptyText?: string
  className?: string
}) {
  const ref = useRef<HTMLPreElement>(null)
  const [following, setFollowing] = useState(true)
  const [showAll, setShowAll] = useState(false)

  // Compute the tailed text and line count. When showAll is true, render all lines;
  // otherwise, tail to TAIL_MAX_LINES.
  const { text, hiddenLines, totalLines } = useMemo(() => {
    if (showAll) {
      return { text: raw, hiddenLines: 0, totalLines: raw ? raw.split('\n').length : 0 }
    }
    const { text: tailedText, hiddenLines: hidden } = tailLines(raw)
    const total = raw ? raw.split('\n').length : 0
    return { text: tailedText, hiddenLines: hidden, totalLines: total }
  }, [raw, showAll])

  // Scroll to the tail when armed. useLayoutEffect: runs after the span re-parse
  // mutates the DOM, before paint — no visible scroll jump.
  useLayoutEffect(() => {
    if (!following) return
    const el = ref.current
    if (el) el.scrollTop = el.scrollHeight
  }, [text, following])

  function handleScroll() {
    const el = ref.current
    if (!el) return
    setFollowing(isAtBottom(el.scrollHeight, el.scrollTop, el.clientHeight))
  }

  function jumpToBottom() {
    const el = ref.current
    if (el) el.scrollTop = el.scrollHeight
    setFollowing(true)
  }

  return (
    <div className="relative flex-1 min-h-0">
      {hiddenLines > 0 && (
        <div className="absolute top-0 inset-x-0 z-10 flex items-center justify-between px-3 py-1.5 bg-gray-900/95 border-b border-gray-700 text-xs text-gray-300">
          <span>Showing last {TAIL_MAX_LINES} lines — {hiddenLines.toLocaleString()} earlier lines hidden</span>
          <button type="button" onClick={() => setShowAll(true)} className="font-semibold text-blue-400 hover:underline">Show all</button>
        </div>
      )}
      {showAll && totalLines > TAIL_MAX_LINES && (
        <div className="absolute top-0 inset-x-0 z-10 flex items-center justify-between px-3 py-1.5 bg-gray-900/95 border-b border-gray-700 text-xs text-gray-300">
          <span>Showing all {totalLines.toLocaleString()} lines</span>
          <button type="button" onClick={() => setShowAll(false)} className="font-semibold text-blue-400 hover:underline">Collapse</button>
        </div>
      )}
      <pre
        ref={ref}
        onScroll={handleScroll}
        className={`h-full text-sm font-mono bg-gray-950 text-gray-300 p-4 overflow-auto leading-relaxed whitespace-pre-wrap min-h-0 ${className}`}
        style={hiddenLines > 0 || (showAll && totalLines > TAIL_MAX_LINES) ? { paddingTop: 'calc(1.5rem + 1.5rem + 1px)' } : {}}
      >
        {raw ? (
          <AnsiText raw={text} />
        ) : isLive ? (
          <span className="text-gray-500">Waiting for output…</span>
        ) : (
          <span className="text-gray-500">{emptyText}</span>
        )}
      </pre>
      {!following && (
        <button
          type="button"
          onClick={jumpToBottom}
          className="absolute bottom-3 right-3 flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-gray-800 text-gray-50 border border-gray-600 rounded-lg shadow-lg hover:bg-gray-700"
        >
          ↓ Jump to bottom
        </button>
      )}
    </div>
  )
}
