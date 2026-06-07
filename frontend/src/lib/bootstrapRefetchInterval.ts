// Pure helper for the node query refetchInterval (#544).
// Returns 3000ms while a bootstrap is actively running, false otherwise.
// Tested via node --experimental-strip-types (tests/unit/test_bootstrap_refetch_interval.ts).

export function bootstrapRefetchInterval(status: string | undefined): number | false {
  return status === 'bootstrapping' ? 3000 : false
}
