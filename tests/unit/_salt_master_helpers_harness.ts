// Harness for testing saltMasterHelpers pure functions.
// Run via: node --experimental-strip-types --no-warnings _salt_master_helpers_harness.ts '<json>'
// Driven by tests/unit/test_salt_master_helpers_521.py.
import { saltMasterBadge, isBootstrapBlocked } from "../../frontend/src/lib/saltMasterHelpers.ts"

const cases: string[] = JSON.parse(process.argv[2])

const results = cases.map((status) => ({
  badge: saltMasterBadge(status),
  blocked: isBootstrapBlocked(status),
}))

console.log(JSON.stringify(results))
