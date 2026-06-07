// Harness for testing masterNodes pure functions.
// Run via: node --experimental-strip-types --no-warnings _master_nodes_559_harness.ts '<json>'
// Driven by tests/unit/test_master_nodes_559.py.
import { mastersByNodeId, isMasterNode, masterHealthSummary } from "../../frontend/src/lib/masterNodes.ts"

interface HarnessInput {
  fn: "mastersByNodeId" | "isMasterNode" | "masterHealthSummary"
  masters?: Array<{ node_id: string | null; status: string }>
  nodeId?: string
}

const cases: HarnessInput[] = JSON.parse(process.argv[2])

const results = cases.map((c) => {
  if (c.fn === "mastersByNodeId") {
    return { result: Array.from(mastersByNodeId(c.masters ?? [])) }
  }
  if (c.fn === "isMasterNode") {
    return { result: isMasterNode(c.nodeId ?? "", c.masters ?? []) }
  }
  if (c.fn === "masterHealthSummary") {
    return { result: masterHealthSummary(c.masters ?? []) }
  }
  return { result: null }
})

console.log(JSON.stringify(results))
