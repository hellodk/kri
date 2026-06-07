/**
 * Pure helper functions for Salt Master node-surfacing — issue #559, epic master-lifecycle.
 * Kept here for unit-testability via node --experimental-strip-types.
 */

/** Minimal shape required — matches SaltMaster from api/saltMasters.ts */
export interface MasterRef {
  node_id: string | null
  status: string
}

/**
 * Returns the set of node IDs that have a linked salt-master.
 * Filters out null / empty node_id values.
 */
export function mastersByNodeId(masters: MasterRef[]): Set<string> {
  const ids = new Set<string>()
  for (const m of masters) {
    if (m.node_id) ids.add(m.node_id)
  }
  return ids
}

/**
 * Returns true when the given node is acting as a salt-master.
 */
export function isMasterNode(nodeId: string, masters: MasterRef[]): boolean {
  return mastersByNodeId(masters).has(nodeId)
}

export interface MasterHealthSummary {
  healthy: number
  degraded: number
  unreachable: number
  unknown: number
  total: number
}

/**
 * Counts master health states from a list of masters.
 * Any status that is not healthy / degraded / unreachable is counted as unknown.
 */
export function masterHealthSummary(masters: { status: string }[]): MasterHealthSummary {
  let healthy = 0
  let degraded = 0
  let unreachable = 0
  let unknown = 0
  for (const m of masters) {
    switch (m.status) {
      case 'healthy':    healthy++;    break
      case 'degraded':   degraded++;   break
      case 'unreachable': unreachable++; break
      default:           unknown++;    break
    }
  }
  return { healthy, degraded, unreachable, unknown, total: masters.length }
}
