// Runs the real tailLines helper under node --experimental-strip-types.
// Reads a JSON array of [raw, max?] arg-arrays from argv[2], prints JSON results.
// Driven by tests/unit/test_log_tail.py.
import { tailLines } from "../../frontend/src/lib/tailLines.ts"

const cases: [string, number?][] = JSON.parse(process.argv[2])
console.log(JSON.stringify(cases.map((a) => tailLines(a[0], a[1]))))
