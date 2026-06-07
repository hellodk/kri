// Harness for testing saltMasterGuard pure function.
// Run via: node --experimental-strip-types --no-warnings _no_master_guard_harness.ts '<json>'
// Driven by tests/unit/test_no_master_guard_538.py.
import { fleetActionsBlocked } from "../../frontend/src/lib/saltMasterGuard.ts"

interface MasterStub {
  enabled: boolean
}

const cases: Array<MasterStub[] | null> = JSON.parse(process.argv[2])

const results = cases.map((masters) => ({
  blocked: fleetActionsBlocked(masters === null ? undefined : masters),
}))

console.log(JSON.stringify(results))
