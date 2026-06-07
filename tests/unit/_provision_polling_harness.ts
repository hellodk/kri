// Drives provisionRefetchInterval under node --experimental-strip-types.
// Reads a JSON array of status strings from argv[2], prints JSON results.
// Driven by tests/unit/test_provision_status_endpoint_558.py.
import { provisionRefetchInterval } from "../../frontend/src/lib/provisionPolling.ts"

const cases: (string | undefined)[] = JSON.parse(process.argv[2])
console.log(JSON.stringify(cases.map((s) => provisionRefetchInterval(s))))
