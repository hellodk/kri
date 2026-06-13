// Shared helpers for the NodeDetail page and its tab panels.
//
// Lives in `pages/nodeDetail/utils.ts` rather than the global `utils/` because
// the meanings here (protected targets, macOS detection, bootstrap status
// styling) are specific to NodeDetail's domain and should not be tempting to
// reuse from unrelated parts of the app.
//
// All values were originally inline in NodeDetail.tsx. They are now extracted
// so the lazy-loaded tab components can import them without pulling the entire
// 2700-line page into the chunk (#arch-nodedetail).

import type { Node } from '../../types'

// Mirror of PendingAction.PROTECTED_TARGETS in
// fleet_platform/models/pending_action.py — kept in sync by the unit test
// tests/unit/test_protected_targets_ui_629.py.
export const PROTECTED_TARGETS = new Set([
  'salt-minion', 'salt-master', 'sshd', 'mdnsresponder', 'configd', 'powerd',
  'securityd', 'trustd', 'opendirectoryd', 'syslogd', 'networkd', 'launchd',
  'kernel_task', 'windowserver', 'exo',
])

export function isProtectedTarget(name: string): boolean {
  if (!name) return false
  const n = name.trim().toLowerCase()
  const bare = n.includes('.') ? n.split('.').pop()! : n
  return PROTECTED_TARGETS.has(n) || PROTECTED_TARGETS.has(bare)
}

export function isMacOSNode(node: Node): boolean {
  return !!(node.macos_version || node.xcode_version)
}

export function fmtBytes(n: number | null): string {
  if (n == null) return '—'
  if (n >= 1_073_741_824) return (n / 1_073_741_824).toFixed(1) + ' GB'
  if (n >= 1_048_576)     return (n / 1_048_576).toFixed(1) + ' MB'
  if (n >= 1_024)         return (n / 1_024).toFixed(1) + ' KB'
  return n + ' B'
}

export const CERT_TYPES = ['code_signing', 'provisioning', 'distribution', 'other']

export const BOOTSTRAP_STATUS_STYLE: Record<string, { label: string; colour: string; bg: string }> = {
  unregistered: { label: 'Not bootstrapped', colour: 'text-gray-500', bg: 'bg-gray-50 border-gray-200' },
  pending:      { label: 'Queued',           colour: 'text-gray-600', bg: 'bg-gray-50 border-gray-200' },
  bootstrapping:{ label: 'Running…',         colour: 'text-brand-600', bg: 'bg-brand-50 border-brand-200' },
  completed:    { label: 'Completed',        colour: 'text-emerald-700', bg: 'bg-emerald-50 border-emerald-200' },
  failed:       { label: 'Failed',           colour: 'text-red-700', bg: 'bg-red-50 border-red-200' },
}

export type Tab =
  | 'overview'
  | 'drift'
  | 'sbom'
  | 'executions'
  | 'bootstrap-history'
  | 'secrets'
  | 'ios'
  | 'services'
  | 'resources'
  | 'processes'
