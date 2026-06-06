// Pure scroll-position helper for log tail-following (#373).
// Tested via node (tests/unit/test_scroll_follow.py).

// True when the scroll position is within `threshold` px of the bottom.
// Used to decide whether to keep auto-following the tail: this is set from real
// onScroll events (user intent), NOT recomputed after content is appended — which
// is what made large output bursts wrongly cancel following on the old detail view.
export function isAtBottom(
  scrollHeight: number,
  scrollTop: number,
  clientHeight: number,
  threshold = 40,
): boolean {
  return scrollHeight - scrollTop - clientHeight < threshold
}
