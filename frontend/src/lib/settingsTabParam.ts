/**
 * Pure helper: resolve a raw ?tab query-param value to a canonical SettingsPage tab name.
 *
 * Rules:
 *   - Legacy 'Bootstrap' and 'Advanced' map to 'Automation' (consolidated in #391).
 *   - Any recognised tab name passes through unchanged.
 *   - Unknown / empty values fall back to 'General'.
 *
 * Kept as a standalone pure function so it can be node-strip tested without
 * importing React or any browser globals.
 */

export const SETTINGS_TABS = [
  'General',
  'Automation',
  'Remote Access',
  'Integrations',
  'Salt Masters',
  'Playbook Library',
  'LLM',
  'Notifications',
] as const

export type SettingsTab = typeof SETTINGS_TABS[number]

export function resolveSettingsTab(raw: string | null | undefined): SettingsTab {
  const value = raw ?? ''
  if (value === 'Bootstrap' || value === 'Advanced') return 'Automation'
  if ((SETTINGS_TABS as readonly string[]).includes(value)) return value as SettingsTab
  return 'General'
}
