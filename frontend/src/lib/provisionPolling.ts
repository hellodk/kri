// Pure helper for the provision-status query refetchInterval (#558).
// Returns 3000ms while a provision run is actively 'running', false otherwise.
// Tested via node --experimental-strip-types (tests/unit/_provision_polling_harness.ts).

export function provisionRefetchInterval(status: string | undefined): number | false {
  return status === 'running' ? 3000 : false
}
