// Runs the real ansibleCardCta helper under node --experimental-strip-types.
// Reads a JSON array of [endpointUrl] arg-arrays from argv[2], prints JSON results.
// Driven by tests/unit/test_ansible_cta_441.py.
import { ansibleCardCta } from "../../frontend/src/lib/ansibleCta.ts"

const cases: [string | null][] = JSON.parse(process.argv[2])
console.log(JSON.stringify(cases.map((a) => ansibleCardCta(a[0]))))
