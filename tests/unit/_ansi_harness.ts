// Test harness: runs the REAL ansiToSpans parser under node --experimental-strip-types.
// Reads a JSON array of input strings from argv[2], prints JSON array of span-arrays.
// Driven by tests/unit/test_ansi_to_spans.py — keeps parser tests behavioral without
// adding a JS test runner (node runs the .ts source directly).
import { ansiToSpans } from "../../frontend/src/lib/ansiToSpans.ts"

const inputs: string[] = JSON.parse(process.argv[2])
console.log(JSON.stringify(inputs.map((s) => ansiToSpans(s))))
