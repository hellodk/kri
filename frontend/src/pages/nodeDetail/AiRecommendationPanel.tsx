import React from 'react'

/**
 * Renders an AI recommendation text with light markdown-style formatting.
 * Bold **text** is highlighted, numbered list items get visual separation,
 * and the overall block is readable without depending on a markdown library.
 *
 * Extracted from NodeDetail.tsx so it can be reused on other pages
 * (see Drift Explorer, future Alerts panel) without dragging the entire
 * NodeDetail bundle in (#arch-nodedetail).
 */
export function AiRecommendationPanel({ text }: { text: string }) {
  const lines = text.split('\n')

  function renderLine(line: string, idx: number) {
    const boldPattern = /\*\*(.+?)\*\*|__(.+?)__/g
    const parts: React.ReactNode[] = []
    let last = 0
    let match: RegExpExecArray | null
    let key = 0
    while ((match = boldPattern.exec(line)) !== null) {
      if (match.index > last) parts.push(line.slice(last, match.index))
      parts.push(
        <strong key={key++} className="font-semibold text-gray-900">
          {match[1] ?? match[2]}
        </strong>,
      )
      last = match.index + match[0].length
    }
    if (last < line.length) parts.push(line.slice(last))

    const isNumbered = /^\s*\d+[.)]\s/.test(line)
    const isBullet = /^\s*[-*]\s/.test(line)
    const isHeading = /^#{1,3}\s/.test(line)

    if (isHeading) {
      const headText = line.replace(/^#{1,3}\s/, '')
      return (
        <p
          key={idx}
          className="text-xs font-bold uppercase tracking-wide text-indigo-700 mt-3 mb-1"
        >
          {headText}
        </p>
      )
    }
    if (isNumbered || isBullet) {
      return (
        <div key={idx} className="flex gap-2 mt-1">
          <span className="text-indigo-400 shrink-0 mt-0.5">{isBullet ? '•' : ''}</span>
          <p className="text-sm text-gray-800 leading-relaxed">
            {parts.length ? parts : line}
          </p>
        </div>
      )
    }
    if (line.trim() === '') return <div key={idx} className="h-2" />

    return (
      <p key={idx} className="text-sm text-gray-800 leading-relaxed mt-0.5">
        {parts.length ? parts : line}
      </p>
    )
  }

  return (
    <div className="bg-white rounded-lg border border-blue-100 p-4 space-y-0.5">
      {/* Lines are derived from splitting the `text` prop; no stable identity exists.
          Index is safe because the whole array is replaced whenever `text` changes. */}
      {lines.map((line, idx) => renderLine(line, idx))}
      <p className="text-xs text-gray-500 mt-3 pt-2 border-t border-gray-100">
        AI-generated — verify before acting. Actions require approval.
      </p>
    </div>
  )
}
