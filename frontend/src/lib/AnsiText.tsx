import { useMemo } from 'react'
import { ansiToSpans } from './ansiToSpans'

// Render ANSI-coloured log text as styled <span> children (#369). Uses React children
// (always escaped by the reconciler) and the style prop — never dangerouslySetInnerHTML —
// because the text originates on remote managed hosts. Parse is memoised on `raw`.
export function AnsiText({ raw }: { raw: string }) {
  const spans = useMemo(() => ansiToSpans(raw), [raw])
  return (
    <>
      {/* Spans are derived from a parsed string and have no stable identity; index is safe since the array is fully replaced when `raw` changes */}
      {spans.map((s, i) => (
        <span
          key={i}
          style={s.color ? { color: s.color } : undefined}
          className={s.bold ? 'font-bold' : undefined}
        >
          {s.text}
        </span>
      ))}
    </>
  )
}
