/**
 * Pure helper functions for Salt Master UI logic — issue #521, epic #523.
 * Kept here for unit-testability via node --experimental-strip-types.
 */

export type SaltMasterStatus = 'healthy' | 'degraded' | 'unreachable' | 'unknown' | string

export interface StatusBadge {
  label: string
  /** Tailwind background color class */
  bgClass: string
  /** Tailwind text color class */
  textClass: string
}

/**
 * Map a salt-master status string to display badge properties.
 * Always returns a visible badge (no gray-400 / low-contrast colors).
 */
export function saltMasterBadge(status: SaltMasterStatus): StatusBadge {
  switch (status) {
    case 'healthy':
      return { label: 'Healthy', bgClass: 'bg-emerald-100', textClass: 'text-emerald-800' }
    case 'degraded':
      return { label: 'Degraded', bgClass: 'bg-amber-100', textClass: 'text-amber-800' }
    case 'unreachable':
      return { label: 'Unreachable', bgClass: 'bg-red-100', textClass: 'text-red-800' }
    case 'unknown':
    default:
      return { label: 'Unknown', bgClass: 'bg-gray-100', textClass: 'text-gray-700' }
  }
}

/**
 * Returns true when the bootstrap button should be disabled because the
 * default salt-master is known to be unreachable.
 *
 * Only blocks on 'unreachable' — unknown/degraded/healthy all allow proceeding.
 */
export function isBootstrapBlocked(status: SaltMasterStatus | null | undefined): boolean {
  return status === 'unreachable'
}
