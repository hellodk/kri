// Runs the real isAtBottom helper under node --experimental-strip-types.
// Reads a JSON array of arg-arrays from argv[2], prints JSON array of booleans.
// Driven by tests/unit/test_scroll_follow.py.
import { isAtBottom } from "../../frontend/src/lib/scrollFollow.ts"

const cases: number[][] = JSON.parse(process.argv[2])
console.log(JSON.stringify(cases.map((a) => isAtBottom(a[0], a[1], a[2], a[3]))))
