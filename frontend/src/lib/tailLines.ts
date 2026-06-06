// Tail-cap helper for the log pane (#370). Pure function, tested via node
// (tests/unit/test_log_tail.py). Rendering 50k+ line logs janks the browser and
// re-parses the whole blob each poll — show only the tail by default.

export const TAIL_MAX_LINES = 500

export function tailLines(raw: string, max = TAIL_MAX_LINES): { text: string; hiddenLines: number } {
  if (!raw) return { text: '', hiddenLines: 0 }
  const lines = raw.split('\n')
  if (lines.length <= max) return { text: raw, hiddenLines: 0 }
  return { text: lines.slice(-max).join('\n'), hiddenLines: lines.length - max }
}
