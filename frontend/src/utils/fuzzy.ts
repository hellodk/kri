/**
 * Lightweight fuzzy matching — no external dependencies.
 *
 * fuzzy(target, query): true if every character of query appears in target
 * in order (not necessarily adjacent). Case-insensitive.
 * Example: fuzzy("bootstrap_mac_mini.yml", "bsmc") → true
 *
 * fuzzyScore(target, query): returns a relevance score > 0 on match, 0 on
 * no-match. Consecutive character matches score exponentially higher so
 * "boot" beats "boo" when ranking results.
 */

export function fuzzy(target: string, query: string): boolean {
  if (!query) return true
  const t = target.toLowerCase()
  const q = query.toLowerCase()
  let j = 0
  for (let i = 0; i < t.length && j < q.length; i++) {
    if (t[i] === q[j]) j++
  }
  return j === q.length
}

export function fuzzyScore(target: string, query: string): number {
  if (!query) return 0
  const t = target.toLowerCase()
  const q = query.toLowerCase()
  let j = 0, score = 0, run = 0
  for (let i = 0; i < t.length && j < q.length; i++) {
    if (t[i] === q[j]) {
      j++
      run++
      score += run * run   // consecutive matches compound: 1 + 4 + 9 …
    } else {
      run = 0
    }
  }
  return j === q.length ? score : 0
}

/** Match against multiple fields; returns the highest score across all. */
export function fuzzyAny(fields: string[], query: string): number {
  return Math.max(...fields.map((f) => fuzzyScore(f, query)))
}
