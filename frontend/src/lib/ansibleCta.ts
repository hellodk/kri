// #441: pure mapping for the Ansible stat card on the Playbooks page.
// Given the configured external Ansible endpoint URL, returns the card's
// status label, hint text, and the Settings route to navigate to on click.
// Ansible is configured under Settings → Integrations (SettingsPage.tsx).

export const ANSIBLE_SETTINGS_ROUTE = '/settings?tab=Integrations'

export interface AnsibleCardCta {
  status: 'Connected' | 'Not configured'
  hint: string
  route: string
}

export function ansibleCardCta(endpointUrl: string | null | undefined): AnsibleCardCta {
  const configured = Boolean(endpointUrl)
  return {
    status: configured ? 'Connected' : 'Not configured',
    hint: configured ? (endpointUrl as string) : 'Set in Settings',
    route: ANSIBLE_SETTINGS_ROUTE,
  }
}
