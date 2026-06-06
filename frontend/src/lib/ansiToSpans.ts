// ansiToSpans — parse ANSI SGR escape codes (as emitted by ansible-playbook with
// ANSIBLE_FORCE_COLOR=1) into styled text runs for safe React rendering (#369).
//
// Pure function, no DOM/React dependency → unit-tested via node (tests/unit/test_ansi_to_spans.py).
// Render the result as React <span> children — never dangerouslySetInnerHTML — so the
// non-ANSI text (which originates on remote managed hosts) is always escaped by React.
//
// Ansible uses only a small SGR subset: reset (0), bold (1), and the 8 basic foreground
// colours (30-37) plus their bright variants (90-97). 256-colour / 24-bit / cursor codes
// never appear. Unknown codes are ignored; malformed sequences degrade to literal text.

export type AnsiSpan = {
  text: string
  color?: string
  bold?: boolean
}

// SGR foreground code -> WCAG-AA hex on bg-gray-950 (#030712). Bright variants map to the
// same readable colour as their normal counterpart. Semantics follow ansible's scheme.
const FG: Record<number, string> = {
  30: '#9CA3AF', 90: '#9CA3AF', // black      -> readable gray
  31: '#F87171', 91: '#F87171', // red        -> failed / unreachable
  32: '#4ADE80', 92: '#4ADE80', // green      -> ok
  33: '#FCD34D', 93: '#FCD34D', // yellow     -> changed
  34: '#60A5FA', 94: '#60A5FA', // blue       -> recap header
  35: '#E879F9', 95: '#E879F9', // magenta    -> warnings
  36: '#67E8F9', 96: '#67E8F9', // cyan       -> skipping
  37: '#F9FAFB', 97: '#F9FAFB', // white      -> default/recap text
}

// eslint-disable-next-line no-control-regex -- intentional: \x1b is the ANSI escape character required for SGR colour sequence parsing
const SGR = /\x1b\[([0-9;]*)m/g

export function ansiToSpans(raw: string): AnsiSpan[] {
  if (!raw) return []
  // Normalise CRLF -> LF and drop lone CR so carriage returns don't render oddly.
  const input = raw.replace(/\r\n/g, '\n').replace(/\r/g, '')

  const spans: AnsiSpan[] = []
  let color: string | undefined
  let bold = false
  let lastIndex = 0
  let m: RegExpExecArray | null

  const push = (text: string) => {
    if (!text) return
    const span: AnsiSpan = { text }
    if (color) span.color = color
    if (bold) span.bold = true
    spans.push(span)
  }

  SGR.lastIndex = 0
  while ((m = SGR.exec(input)) !== null) {
    push(input.slice(lastIndex, m.index))
    lastIndex = SGR.lastIndex
    const params = m[1] === '' ? [0] : m[1].split(';').map((p) => parseInt(p, 10))
    for (const p of params) {
      if (p === 0) {
        color = undefined
        bold = false
      } else if (p === 1) {
        bold = true
      } else if (p in FG) {
        color = FG[p]
      }
      // any other code (e.g. 4=underline) is ignored
    }
  }
  push(input.slice(lastIndex))
  return spans
}
