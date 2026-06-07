/**
 * Pure helper for no-salt-master guard — issue #538, epic #537.
 * Kept here for unit-testability via node --experimental-strip-types.
 */

/**
 * Returns true when fleet actions should be blocked.
 *
 * Blocks only when masters is *defined* (i.e. data has loaded) and every
 * entry has enabled === false (or there are zero entries).
 *
 * Treats undefined / loading state as NOT blocked to avoid a flash on
 * initial page load before the query resolves.
 */
export function fleetActionsBlocked(
  masters: { enabled: boolean }[] | undefined,
): boolean {
  if (masters === undefined) return false
  return masters.filter((m) => m.enabled).length === 0
}
