// Drives bootstrapRefetchInterval under node --experimental-strip-types.
// Reads a JSON array of status strings from argv[2], prints JSON results.
// Driven by tests/unit/test_bootstrap_logs_live_544.py.
import { bootstrapRefetchInterval } from "../../frontend/src/lib/bootstrapRefetchInterval.ts"

const cases: (string | undefined)[] = JSON.parse(process.argv[2])
console.log(JSON.stringify(cases.map((s) => bootstrapRefetchInterval(s))))
