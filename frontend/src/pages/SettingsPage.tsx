import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { resolveSettingsTab, type SettingsTab } from '../lib/settingsTabParam'
import { Skeleton } from '../components/Skeleton'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ansibleApi } from '../api/ansible'
import { playbookSourcesApi, type PlaybookSource, type PlaybookSourceValidateResponse } from '../api/playbookSources'
import { credentialsApi, type Credential } from '../api/credentials'
import { llmApi, type LLMEndpoint } from '../api/llm'
import { LLMEndpointForm } from '../components/LLMEndpointForm'
import { SecretInput } from '../components/SecretInput'
import { useToastStore } from '../stores/toastStore'
import { api } from '../api/client'
import { buildsApi } from '../api/builds'
import { PlaybookLibraryTab } from './PlaybookLibraryTab'
import { SaltMastersTab } from './SaltMastersTab'

function UrlStatusPill({ status, checking }: { status?: { ok: boolean; latency_ms: number | null; error?: string } | null; checking: boolean }) {
  if (checking) return <span className="text-xs text-gray-400 flex items-center gap-1"><span className="inline-block animate-spin">⟳</span> Checking</span>
  if (!status) return null
  if (status.ok) return (
    <span className="text-xs font-medium text-emerald-600 flex items-center gap-1">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
      {status.latency_ms != null ? `${status.latency_ms}ms` : 'OK'}
    </span>
  )
  return (
    <span className="text-xs font-medium text-red-600 flex items-center gap-1">
      <span className="w-1.5 h-1.5 rounded-full bg-red-500 inline-block" />
      {status.error ?? 'Unreachable'}
    </span>
  )
}

export function SettingsPage() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [searchParams, setSearchParams] = useSearchParams()
  const [kriApiUrl, setKriApiUrl] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [ansibleEndpoint, setAnsibleEndpoint] = useState('')
  const [ansibleToken, setAnsibleToken] = useState('')
  const [playbooksDir, setPlaybooksDir] = useState('')
  const [pillarDir, setPillarDir] = useState('')
  const [cxoneUrl, setCxoneUrl] = useState('')
  const [cxoneToken, setCxoneToken] = useState('')
  const [sonarUrl, setSonarUrl] = useState('')
  const [sonarToken, setSonarToken] = useState('')
  const [licensePolicy, setLicensePolicy] = useState('permissive')
  const [vncEnabled, setVncEnabled] = useState(false)
  const [oidcEnabled, setOidcEnabled] = useState(false)
  const [oidcIssuer, setOidcIssuer] = useState('')
  const [oidcClientId, setOidcClientId] = useState('')
  const [oidcClientSecret, setOidcClientSecret] = useState('')
  const [oidcRolePrefix, setOidcRolePrefix] = useState('kri-')
  const [timezone, setTimezone] = useState(() => localStorage.getItem('kri_timezone') ?? '')
  // Email digest settings
  const [smtpHost, setSmtpHost] = useState('')
  const [smtpPort, setSmtpPort] = useState('587')
  const [smtpUsername, setSmtpUsername] = useState('')
  const [smtpPassword, setSmtpPassword] = useState('')
  const [smtpFrom, setSmtpFrom] = useState('')
  const [digestRecipients, setDigestRecipients] = useState('')
  const [jenkinsSecret, setJenkinsSecret] = useState('')
  const [digestSending, setDigestSending] = useState(false)
  const [testEmailSending, setTestEmailSending] = useState(false)
  const [testEmailTo, setTestEmailTo] = useState('')
  const [testEmailResult, setTestEmailResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [llmEmbedBaseUrl, setLlmEmbedBaseUrl] = useState('')
  const [embedUrlStatus, setEmbedUrlStatus] = useState<{ ok: boolean; latency_ms: number | null; error?: string } | null>(null)
  const [embedUrlChecking, setEmbedUrlChecking] = useState(false)
  const embedDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [ansibleStatus, setAnsibleStatus] = useState<{ ok: boolean; latency_ms: number | null; error?: string } | null>(null)
  const [ansibleChecking, setAnsibleChecking] = useState(false)
  const ansibleDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [sonarStatus, setSonarStatus] = useState<{ ok: boolean; latency_ms: number | null; error?: string } | null>(null)
  const [sonarChecking, setSonarChecking] = useState(false)
  const sonarDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [cxoneStatus, setCxoneStatus] = useState<{ ok: boolean; latency_ms: number | null; error?: string } | null>(null)
  const [cxoneChecking, setCxoneChecking] = useState(false)
  const cxoneDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: ansibleApi.getSettings,
  })

  useEffect(() => {
    if (data) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- populating form fields from saved settings on load; refactor tracked in #380 follow-up
      if (data.kri_api_url) setKriApiUrl(data.kri_api_url)
      if (data.ssh_bootstrap_username) setUsername(data.ssh_bootstrap_username)
      if (data.ansible_endpoint_url) setAnsibleEndpoint(data.ansible_endpoint_url)
      if (data.playbooks_dir) setPlaybooksDir(data.playbooks_dir)
      if (data.pillar_dir) setPillarDir(data.pillar_dir)
      if (data.cxone_url) setCxoneUrl(data.cxone_url)
      if (data.sonarqube_url) setSonarUrl(data.sonarqube_url)
      if (data.license_policy) setLicensePolicy(data.license_policy)
      if (data.vnc_enabled !== undefined) setVncEnabled(data.vnc_enabled)
      if (data.oidc_enabled !== undefined) setOidcEnabled(data.oidc_enabled)
      if (data.oidc_issuer_url) setOidcIssuer(data.oidc_issuer_url)
      if (data.oidc_client_id) setOidcClientId(data.oidc_client_id)
      if (data.oidc_role_prefix) setOidcRolePrefix(data.oidc_role_prefix)
      if (data.smtp_host) setSmtpHost(data.smtp_host)
      if (data.smtp_port) setSmtpPort(data.smtp_port)
      if (data.smtp_username) setSmtpUsername(data.smtp_username)
      if (data.smtp_from) setSmtpFrom(data.smtp_from)
      if (data.digest_recipients) setDigestRecipients(data.digest_recipients)
      if (data.llm_embed_base_url) setLlmEmbedBaseUrl(data.llm_embed_base_url)
      if (data.ansible_endpoint_url) checkAnsible(data.ansible_endpoint_url)
      if (data.sonarqube_url) checkSonar(data.sonarqube_url)
      if (data.cxone_url) checkCxone(data.cxone_url)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  // Connectivity probes run on the BACKEND (#362) — the browser cannot reach
  // internal services (Salt API, Ansible, Sonar) due to Same-Origin Policy/CORS.
  async function probe(target: string, port?: number): Promise<{ ok: boolean; latency_ms: number | null; error?: string }> {
    const resp = await api.post<{ ok: boolean; latency_ms: number | null; error?: string }>(
      '/api/v1/settings/check-connectivity',
      { target, port },
    )
    return resp
  }

  async function checkEmbedUrl(url?: string) {
    const target = (url ?? llmEmbedBaseUrl).trim()
    if (!target) { setEmbedUrlStatus(null); return }
    setEmbedUrlChecking(true)
    try {
      const r = await probe(`${target.replace(/\/+$/, '')}/v1/models`)
      setEmbedUrlStatus({ ok: r.ok, latency_ms: r.latency_ms })
    } catch {
      setEmbedUrlStatus({ ok: false, latency_ms: null, error: 'Unreachable' })
    } finally {
      setEmbedUrlChecking(false)
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- triggering connectivity check when embed URL changes; refactor tracked in #380 follow-up
    if (llmEmbedBaseUrl) checkEmbedUrl(llmEmbedBaseUrl)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [llmEmbedBaseUrl])

  async function checkAnsible(url?: string) {
    const target = (url ?? ansibleEndpoint).trim()
    if (!target) { setAnsibleStatus(null); return }
    setAnsibleChecking(true)
    try {
      const r = await probe(target)
      setAnsibleStatus({ ok: r.ok, latency_ms: r.latency_ms })
    } catch {
      setAnsibleStatus({ ok: false, latency_ms: null, error: 'Unreachable' })
    } finally {
      setAnsibleChecking(false)
    }
  }

  async function checkSonar(url?: string) {
    const target = (url ?? sonarUrl).trim()
    if (!target) { setSonarStatus(null); return }
    setSonarChecking(true)
    try {
      const r = await probe(`${target.replace(/\/+$/, '')}/api/system/status`)
      setSonarStatus({ ok: r.ok, latency_ms: r.latency_ms })
    } catch {
      setSonarStatus({ ok: false, latency_ms: null, error: 'Unreachable' })
    } finally {
      setSonarChecking(false)
    }
  }

  async function checkCxone(url?: string) {
    const target = (url ?? cxoneUrl).trim()
    if (!target) { setCxoneStatus(null); return }
    setCxoneChecking(true)
    try {
      const r = await probe(target)
      setCxoneStatus({ ok: r.ok, latency_ms: r.latency_ms })
    } catch {
      setCxoneStatus({ ok: false, latency_ms: null, error: 'Unreachable' })
    } finally {
      setCxoneChecking(false)
    }
  }

  const saveMutation = useMutation({
    mutationFn: () => ansibleApi.updateSettings({
      kri_api_url: kriApiUrl || undefined,
      ssh_bootstrap_username: username || undefined,
      ssh_bootstrap_password: password || undefined,
      ansible_endpoint_url: ansibleEndpoint || undefined,
      ansible_api_token: ansibleToken || undefined,
      playbooks_dir: playbooksDir || undefined,
      pillar_dir: pillarDir || undefined,
      cxone_url: cxoneUrl || undefined,
      cxone_api_token: cxoneToken || undefined,
      sonarqube_url: sonarUrl || undefined,
      sonarqube_token: sonarToken || undefined,
      license_policy: licensePolicy || undefined,
      vnc_enabled: vncEnabled,
      oidc_enabled: oidcEnabled,
      oidc_issuer_url: oidcIssuer || undefined,
      oidc_client_id: oidcClientId || undefined,
      oidc_client_secret: oidcClientSecret || undefined,
      oidc_role_prefix: oidcRolePrefix || undefined,
      smtp_host: smtpHost || undefined,
      smtp_port: smtpPort || undefined,
      smtp_username: smtpUsername || undefined,
      smtp_password: smtpPassword || undefined,
      smtp_from: smtpFrom || undefined,
      digest_recipients: digestRecipients || undefined,
      jenkins_ingest_secret: jenkinsSecret || undefined,
      llm_embed_base_url: llmEmbedBaseUrl || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      toast('Settings saved')
      setPassword('')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const computedIngestUrl = kriApiUrl
    ? `${kriApiUrl.replace(/\/$/, '')}/api/v1/ingest/grains`
    : null

  const TABS = ['General', 'Automation', 'Remote Access', 'Integrations', 'Salt Masters', 'Playbook Library', 'LLM', 'Notifications'] as const
  type Tab = SettingsTab

  const [activeTab, setActiveTab] = useState<Tab>(() =>
    resolveSettingsTab(searchParams.get('tab'))
  )

  // Sync active tab when the ?tab query param changes while SettingsPage stays mounted.
  // Guard against a loop: only call setActiveTab when the resolved value differs from
  // the current tab (handleTabChange already sets both state + URL, so this only fires
  // for external navigation — back/forward, links, programmatic pushes).
  // Legacy aliases 'Bootstrap' and 'Advanced' are mapped to 'Automation' by resolveSettingsTab.
  useEffect(() => {
    const resolved = resolveSettingsTab(searchParams.get('tab'))
    if (resolved !== activeTab) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing derived tab state from URL search params (external navigation source); guard prevents loop
      setActiveTab(resolved)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab)
    setSearchParams({ tab }, { replace: true })
  }

  if (isLoading) return <div className="p-6"><Skeleton rows={8} /></div>

  const inputClass = 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600'
  const monoInputClass = inputClass + ' font-mono'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure the kri fleet platform.</p>
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-gray-200">
        {TABS.map(tab => (
          <button key={tab} onClick={() => handleTabChange(tab)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === tab
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* General tab */}
      {activeTab === 'General' && (
        <div className="space-y-6">
          {/* kri External URL */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">kri External URL</h2>
              <p className="text-sm text-gray-500 mt-1">
                The URL that Mac Minis use to call back to this kri server. Used to build the ingest endpoint
                that Salt minions POST grain data to. Must be reachable from all managed nodes — use the
                Tailscale IP or a LAN address, not <code className="text-xs bg-gray-100 px-1 rounded">localhost</code>.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">kri server URL</label>
              <input
                type="text"
                value={kriApiUrl}
                onChange={(e) => setKriApiUrl(e.target.value)}
                placeholder="http://100.89.50.27  or  http://kri.fleet.local"
                className={monoInputClass}
              />
              <p className="text-xs text-gray-400 mt-1">Include the scheme (<code>http://</code> or <code>https://</code>). No trailing slash.</p>
            </div>
            {computedIngestUrl && (
              <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 flex items-center gap-2">
                <span className="text-xs text-gray-400 shrink-0">Computed ingest URL:</span>
                <code className="text-xs font-mono text-brand-700 truncate">{computedIngestUrl}</code>
              </div>
            )}
          </div>

          {/* Display Timezone */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Display Timezone</h2>
              <p className="text-sm text-gray-500 mt-1">
                Controls how timestamps are displayed throughout the dashboard. Stored in your browser — not synced to the server.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Timezone</label>
              <select
                value={timezone}
                onChange={(e) => {
                  const tz = e.target.value
                  setTimezone(tz)
                  if (tz) {
                    localStorage.setItem('kri_timezone', tz)
                  } else {
                    localStorage.removeItem('kri_timezone')
                  }
                  toast('Timezone updated')
                }}
                className={inputClass}
              >
                <option value="">Browser default ({Intl.DateTimeFormat().resolvedOptions().timeZone})</option>
                <option value="UTC">UTC</option>
                <option value="America/Los_Angeles">US/Pacific (America/Los_Angeles)</option>
                <option value="America/New_York">US/Eastern (America/New_York)</option>
                <option value="America/Chicago">US/Central (America/Chicago)</option>
                <option value="Europe/London">Europe/London</option>
                <option value="Europe/Amsterdam">Europe/Amsterdam</option>
                <option value="Asia/Kolkata">Asia/Kolkata (IST)</option>
                <option value="Asia/Singapore">Asia/Singapore</option>
                <option value="Australia/Sydney">Australia/Sydney</option>
              </select>
              <p className="text-xs text-gray-400 mt-1">Changes apply immediately — no save needed.</p>
            </div>
          </div>
        </div>
      )}

      {/* Automation tab — consolidates former Bootstrap + Advanced tabs (#391) */}
      {activeTab === 'Automation' && (
        <div className="space-y-6">
          {/* Credentials (formerly Advanced) */}
          <CredentialsSection />

          {/* Default SSH Bootstrap Credentials (formerly Bootstrap tab) */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Default SSH Bootstrap Credentials</h2>
              <p className="text-sm text-gray-500 mt-1">
                Used as fallback when a node has no per-node SSH credentials set.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">macOS admin username</label>
              <input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                placeholder="localadmin" className={inputClass} />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                macOS admin password
                <span className="ml-2 text-xs font-normal text-gray-400">(stored encrypted, not shown after save)</span>
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Leave blank to keep existing"
                  className={inputClass + ' pr-16'}
                />
                <button type="button" onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1">
                  {showPassword ? (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21" />
                    </svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* Controller SSH public key */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-3">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Controller SSH Public Key</h2>
              <p className="text-sm text-gray-500 mt-1">
                Auto-generated key deployed to all Mac Minis during bootstrap via{' '}
                <code className="text-xs bg-gray-100 px-1 rounded">authorized_key</code>.
              </p>
            </div>
            {data?.controller_pubkey ? (
              <div className="relative">
                <pre className="text-xs font-mono bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto text-gray-700 whitespace-pre-wrap break-all">
                  {data.controller_pubkey}
                </pre>
                <button
                  onClick={() => { navigator.clipboard.writeText(data.controller_pubkey!); toast('Copied') }}
                  className="absolute top-2 right-2 text-xs text-gray-400 hover:text-gray-600 bg-white border border-gray-200 rounded px-2 py-0.5"
                >
                  Copy
                </button>
              </div>
            ) : (
              <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
                No keypair generated yet. Save settings once to generate the controller keypair.
              </p>
            )}
          </div>

          {/* Pillar directory */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Salt Pillar Directory</h2>
              <p className="text-sm text-gray-500 mt-1">
                kri writes a per-node <code className="text-xs bg-gray-100 px-1 rounded">&lt;minion_id&gt;.sls</code> file here before every bootstrap.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Path to Salt pillar directory</label>
              <input type="text" value={pillarDir} onChange={(e) => setPillarDir(e.target.value)}
                placeholder="/srv/salt/pillar  (default)"
                className={monoInputClass} />
              <p className="text-xs text-gray-400 mt-1">Must be writable by the kri process.</p>
            </div>
          </div>

          {/* Playbooks directory */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Playbooks Directory</h2>
              <p className="text-sm text-gray-500 mt-1">Override the directory kri scans for Ansible playbooks and roles.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Path to playbooks &amp; roles</label>
              <input type="text" value={playbooksDir} onChange={(e) => setPlaybooksDir(e.target.value)}
                placeholder="/home/user/my-playbooks  (default: <repo>/playbooks)"
                className={monoInputClass} />
              <p className="text-xs text-gray-400 mt-1">
                Roles must be in a <code>roles/</code> subdirectory.
              </p>
              <p className="text-xs text-gray-400 mt-1">
                Paths are auto-translated inside Docker: <code>/home/dk/Documents/git/pulse</code> → <code>/mnt/pulse</code>. Enter the host path; kri maps it automatically.
              </p>
            </div>
          </div>

          {/* Salt Allowlist / Denylist (formerly Advanced) */}
          <SaltAllowlistSection />
          <SaltDenylistSection />

          {/* Playbook Sources (formerly Advanced) */}
          <PlaybookSourcesSection />
        </div>
      )}

      {/* Remote Access tab */}
      {activeTab === 'Remote Access' && (
        <div className="space-y-6">
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Remote Access</h2>
              <p className="text-sm text-gray-500 mt-1">
                Control which remote access methods are available to operators.
                Changes take effect immediately after saving.
              </p>
            </div>

            <div className="flex items-center justify-between py-3 border-b border-gray-100">
              <div>
                <p className="text-sm font-medium text-gray-900">WebSSH Terminal</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Browser-based SSH with keystroke recording and command blocking.
                  Always enabled — cannot be disabled.
                </p>
              </div>
              <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded font-medium">Always on</span>
            </div>

            <div className="flex items-center justify-between py-3">
              <div>
                <p className="text-sm font-medium text-gray-900">VNC Screen Share</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Full graphical desktop access via browser (noVNC). Requires Screen Sharing
                  to be enabled on the Mac Mini. Sessions are logged but <strong>cannot be command-blocked</strong>.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setVncEnabled(!vncEnabled)}
                className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
                  vncEnabled ? 'bg-brand-600' : 'bg-gray-300'
                }`}
                role="switch"
                aria-checked={vncEnabled}
              >
                <span
                  className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ${
                    vncEnabled ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>

            {vncEnabled && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-700">
                VNC sessions are recorded but commands cannot be blocked (graphical pixel stream).
                Ensure your security policy allows unfiltered screen access before enabling.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Integrations tab */}
      {activeTab === 'Integrations' && (
        <div className="space-y-6">
          {/* Security Integrations */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Security Integrations</h2>
              <p className="text-sm text-gray-500 mt-1">
                Connect Checkmarx One (CxOne) and SonarQube for enhanced vulnerability and license scanning.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">CxOne URL</label>
                <div className="flex items-center gap-2">
                  <input type="text" value={cxoneUrl}
                    onChange={e => {
                      setCxoneUrl(e.target.value)
                      if (cxoneDebounceRef.current) clearTimeout(cxoneDebounceRef.current)
                      cxoneDebounceRef.current = setTimeout(() => checkCxone(e.target.value), 1000)
                    }}
                    placeholder="https://us.cxone.net" className={`${inputClass} flex-1`} />
                  <UrlStatusPill status={cxoneStatus} checking={cxoneChecking} />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  CxOne API Token <span className="text-xs text-gray-400 font-normal">(encrypted)</span>
                </label>
                <SecretInput value={cxoneToken} onChange={setCxoneToken}
                  placeholder="Leave blank to keep existing" className={inputClass} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">SonarQube URL</label>
                <div className="flex items-center gap-2">
                  <input type="text" value={sonarUrl}
                    onChange={e => {
                      setSonarUrl(e.target.value)
                      if (sonarDebounceRef.current) clearTimeout(sonarDebounceRef.current)
                      sonarDebounceRef.current = setTimeout(() => checkSonar(e.target.value), 1000)
                    }}
                    placeholder="http://sonarqube.utilities.svc.cluster.local:9000" className={`${inputClass} flex-1`} />
                  <UrlStatusPill status={sonarStatus} checking={sonarChecking} />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  SonarQube Token <span className="text-xs text-gray-400 font-normal">(encrypted)</span>
                </label>
                <SecretInput value={sonarToken} onChange={setSonarToken}
                  placeholder="Leave blank to keep existing" className={inputClass} />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">License Policy</label>
              <select value={licensePolicy} onChange={e => setLicensePolicy(e.target.value)} className={inputClass}>
                <option value="permissive">Permissive - flag GPL only</option>
                <option value="strict">Strict - flag GPL + LGPL + unknown</option>
              </select>
              <p className="text-xs text-gray-400 mt-1">Controls which licenses are flagged as "high risk" in the Security dashboard.</p>
            </div>
          </div>

          {/* OIDC / SSO */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-gray-900">OIDC / SSO</h2>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={oidcEnabled}
                  onChange={(e) => setOidcEnabled(e.target.checked)}
                  className="accent-brand-600 w-4 h-4" />
                <span className="text-sm text-gray-600">Enable</span>
              </label>
            </div>
            {oidcEnabled && (
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Issuer URL</label>
                  <input type="text" value={oidcIssuer} onChange={(e) => setOidcIssuer(e.target.value)}
                    placeholder="https://keycloak.example.com/realms/kri"
                    className={inputClass} />
                  <p className="text-xs text-gray-400 mt-1">Keycloak realm URL — kri will fetch the discovery document from here.</p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Client ID</label>
                  <input type="text" value={oidcClientId} onChange={(e) => setOidcClientId(e.target.value)}
                    placeholder="kri-app"
                    className={inputClass} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Client Secret <span className="text-xs font-normal text-gray-400">(stored encrypted, leave blank to keep)</span>
                  </label>
                  <SecretInput value={oidcClientSecret}
                    onChange={setOidcClientSecret}
                    placeholder="Leave blank to keep existing"
                    className={inputClass} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Role prefix</label>
                  <input type="text" value={oidcRolePrefix} onChange={(e) => setOidcRolePrefix(e.target.value)}
                    placeholder="kri-"
                    className={inputClass} />
                  <p className="text-xs text-gray-400 mt-1">
                    Keycloak realm roles with this prefix are mapped to kri roles.
                    Example: <code className="text-xs bg-gray-100 px-1 rounded">kri-admin</code> → <code className="text-xs bg-gray-100 px-1 rounded">admin</code>
                  </p>
                </div>
              </div>
            )}
            {!oidcEnabled && (
              <p className="text-sm text-gray-400">Enable OIDC to configure single sign-on via Keycloak.</p>
            )}
          </div>

          {/* External Ansible endpoint */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">External Ansible Endpoint</h2>
              <p className="text-sm text-gray-500 mt-1">
                Configure an AWX or Ansible Tower endpoint. When set, kri sends playbook jobs to this endpoint instead of running <code className="text-xs bg-gray-100 px-1 rounded">ansible-runner</code> locally.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Endpoint URL</label>
              <div className="flex items-center gap-2">
                <input type="text" value={ansibleEndpoint}
                  onChange={(e) => {
                    setAnsibleEndpoint(e.target.value)
                    if (ansibleDebounceRef.current) clearTimeout(ansibleDebounceRef.current)
                    ansibleDebounceRef.current = setTimeout(() => checkAnsible(e.target.value), 1000)
                  }}
                  placeholder="https://awx.example.com" className={`${inputClass} flex-1`} />
                <UrlStatusPill status={ansibleStatus} checking={ansibleChecking} />
              </div>
              <p className="text-xs text-gray-400 mt-1">Leave blank to use local ansible-runner.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                API Token <span className="ml-2 text-xs font-normal text-gray-400">(stored encrypted)</span>
              </label>
              <SecretInput value={ansibleToken} onChange={setAnsibleToken}
                placeholder="Leave blank to keep existing" className={inputClass} />
            </div>
          </div>
        </div>
      )}

      {/* Salt Masters tab */}
      {activeTab === 'Salt Masters' && <SaltMastersTab />}

      {/* Playbook Library tab */}
      {activeTab === 'Playbook Library' && (
        <div className="space-y-4">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Playbook Library</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Enable playbooks from configured sources to make them available on the Playbooks page.
            </p>
          </div>
          <PlaybookLibraryTab />
        </div>
      )}

      {/* LLM tab */}
      {activeTab === 'LLM' && (
        <div className="space-y-6">
          <LLMEndpointsSection />

          {/* RAG Embedding endpoint */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">RAG Embedding</h2>
              <p className="text-sm text-gray-500 mt-1">
                Configure the embedding model endpoint for the RAG knowledge-plane retrieval pipeline.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Embedding Model URL
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={llmEmbedBaseUrl}
                  onChange={(e) => {
                    setLlmEmbedBaseUrl(e.target.value)
                    if (embedDebounceRef.current) clearTimeout(embedDebounceRef.current)
                    embedDebounceRef.current = setTimeout(() => checkEmbedUrl(e.target.value), 1000)
                  }}
                  placeholder="http://192.168.1.23:52415"
                  className={inputClass}
                />
                <StatusPill result={embedUrlStatus ?? undefined} checking={embedUrlChecking} />
              </div>
              <p className="text-xs text-gray-400 mt-1">
                OpenAI-compatible endpoint for <code className="text-xs bg-gray-100 px-1 rounded">nomic-embed-text-v1.5</code> (used for RAG retrieval).
                Leave blank to disable semantic retrieval — fleet context will use live DB facts only.
              </p>
            </div>
            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50 shadow-sm"
            >
              {saveMutation.isPending ? 'Saving…' : 'Save Embedding URL'}
            </button>
          </div>
        </div>
      )}

      {/* Notifications tab */}
      {activeTab === 'Notifications' && (
        <div className="space-y-6">

          {/* Jenkins Ingest */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Jenkins Build Ingest</h2>
              <p className="text-sm text-gray-500 mt-1">
                Configure your Jenkins jobs to POST build results to kri after each build.
                No polling — Jenkins pushes data to you.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Ingest Endpoint
              </label>
              <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 flex items-center gap-2">
                <code className="text-xs font-mono text-brand-700 truncate">
                  {kriApiUrl ? `${kriApiUrl.replace(/\/$/, '')}/api/v1/builds/ingest` : 'Set kri server URL in General tab first'}
                </code>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Shared Secret (X-Jenkins-Secret header)
              </label>
              <SecretInput
                value={jenkinsSecret}
                onChange={setJenkinsSecret}
                placeholder="Enter new secret to set or rotate"
                className={inputClass}
              />
              <p className="text-xs text-gray-400 mt-1">
                Set this once, copy it to Jenkins as a credential, then add it to each job's
                <code className="mx-1 text-xs bg-gray-100 px-1 rounded">X-Jenkins-Secret</code>
                header. Secret is stored encrypted.
              </p>
            </div>
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <p className="text-sm font-semibold text-blue-900 mb-2">Jenkins Pipeline Snippet</p>
              <pre className="text-xs font-mono text-blue-800 overflow-x-auto whitespace-pre">{`post {
  always {
    script {
      def payload = groovy.json.JsonOutput.toJson([
        job_name    : env.JOB_NAME,
        build_number: env.BUILD_NUMBER.toInteger(),
        result      : currentBuild.result ?: 'SUCCESS',
        duration_ms : currentBuild.duration,
        started_at  : new Date(currentBuild.startTimeInMillis)
                        .format("yyyy-MM-dd'T'HH:mm:ss'Z'",
                                TimeZone.getTimeZone('UTC')),
        test_pass   : currentBuild.testResultAction?.passCount,
        test_fail   : currentBuild.testResultAction?.failCount,
        test_total  : currentBuild.testResultAction?.totalCount,
        node_name   : env.NODE_NAME,
        branch      : env.GIT_BRANCH,
      ])
      httpRequest(
        url         : "\${env.KRI_API_URL}/api/v1/builds/ingest",
        httpMode    : 'POST',
        contentType : 'APPLICATION_JSON',
        requestBody : payload,
        customHeaders: [[name: 'X-Jenkins-Secret',
                         value: env.KRI_JENKINS_SECRET]],
        validResponseCodes: '200'
      )
    }
  }
}`}</pre>
              <p className="text-xs text-blue-700 mt-2">
                Add <code className="bg-blue-100 px-1 rounded">KRI_API_URL</code> and{' '}
                <code className="bg-blue-100 px-1 rounded">KRI_JENKINS_SECRET</code> as Jenkins
                credentials (Secret Text). Requires the{' '}
                <a
                  href="https://plugins.jenkins.io/http_request/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                >HTTP Request Plugin</a>.
              </p>
            </div>
          </div>

          {/* SMTP settings */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div>
              <h2 className="text-base font-semibold text-gray-900">Email (SMTP)</h2>
              <p className="text-sm text-gray-500 mt-1">
                Settings for the weekly fleet digest email. Sent every Monday at 08:00 UTC.
              </p>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">SMTP Host</label>
                <input
                  type="text"
                  value={smtpHost}
                  onChange={(e) => setSmtpHost(e.target.value)}
                  placeholder="smtp.gmail.com"
                  className={monoInputClass}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Port</label>
                <input
                  type="text"
                  value={smtpPort}
                  onChange={(e) => setSmtpPort(e.target.value)}
                  placeholder="587"
                  className={monoInputClass}
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">SMTP Username</label>
              <input
                type="text"
                value={smtpUsername}
                onChange={(e) => setSmtpUsername(e.target.value)}
                placeholder="alerts@yourorg.com"
                className={monoInputClass}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">SMTP Password</label>
              <SecretInput
                value={smtpPassword}
                onChange={setSmtpPassword}
                placeholder="Enter password to set or update"
                className={inputClass}
              />
              <p className="text-xs text-gray-400 mt-1">Stored encrypted. Leave blank to keep existing.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">From Address</label>
              <input
                type="text"
                value={smtpFrom}
                onChange={(e) => setSmtpFrom(e.target.value)}
                placeholder="kri Fleet Platform <kri@yourorg.com>"
                className={monoInputClass}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Digest Recipients
              </label>
              <input
                type="text"
                value={digestRecipients}
                onChange={(e) => setDigestRecipients(e.target.value)}
                placeholder="manager@yourorg.com, cto@yourorg.com"
                className={monoInputClass}
              />
              <p className="text-xs text-gray-400 mt-1">Comma-separated list of email addresses.</p>
            </div>
          </div>

          {/* Save + Test */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
            <div className="flex items-center gap-3">
              <button
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending}
                className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
              >
                {saveMutation.isPending ? 'Saving…' : 'Save Notification Settings'}
              </button>
              <button
                onClick={async () => {
                  setDigestSending(true)
                  try {
                    await buildsApi.triggerDigest()
                    toast('Digest queued — check your inbox in a moment')
                  } catch {
                    toast('Failed to queue digest', 'error')
                  } finally {
                    setDigestSending(false)
                  }
                }}
                disabled={digestSending}
                className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 disabled:opacity-50 border border-gray-200"
              >
                {digestSending ? 'Sending…' : 'Send Test Digest Now'}
              </button>
            </div>

            {/* Send test email — #417 */}
            <div className="border-t border-gray-100 pt-4 space-y-3">
              <div>
                <p className="text-sm font-medium text-gray-900">Send test email</p>
                <p className="text-xs text-gray-500 mt-0.5">
                  Sends a small confirmation email through the SMTP settings above.
                  Leave the recipient blank to send to the configured digest recipients.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={testEmailTo}
                  onChange={(e) => { setTestEmailTo(e.target.value); setTestEmailResult(null) }}
                  placeholder="Override recipient (optional)"
                  className={`${monoInputClass} flex-1`}
                />
                <button
                  onClick={async () => {
                    setTestEmailSending(true)
                    setTestEmailResult(null)
                    try {
                      const res = await api.post<{ status: string; detail: string }>(
                        '/api/v1/settings/test-email',
                        { to: testEmailTo.trim() || null },
                      )
                      setTestEmailResult({ ok: true, message: res.detail ?? 'Test email sent' })
                    } catch (e: unknown) {
                      const msg = e instanceof Error ? e.message : 'Failed to send test email'
                      setTestEmailResult({ ok: false, message: msg })
                    } finally {
                      setTestEmailSending(false)
                    }
                  }}
                  disabled={testEmailSending}
                  className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 disabled:opacity-50 border border-gray-200 whitespace-nowrap"
                >
                  {testEmailSending ? 'Sending…' : 'Send test email'}
                </button>
              </div>
              {testEmailResult && (
                <p className={`text-xs font-medium ${testEmailResult.ok ? 'text-emerald-700' : 'text-red-700'}`}>
                  {testEmailResult.ok ? '✓' : '✗'} {testEmailResult.message}
                </p>
              )}
            </div>
          </div>

        </div>
      )}

      {/* Save button — visible for all tabs except LLM, Notifications, Playbook Library, and Salt Masters (which manage their own state) */}
      {activeTab !== 'LLM' && activeTab !== 'Notifications' && activeTab !== 'Playbook Library' && activeTab !== 'Salt Masters' && (
        <div className="flex justify-end pt-2">
          <button
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
            className="px-6 py-2.5 bg-brand-600 text-white rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50 shadow-sm"
          >
            {saveMutation.isPending ? 'Saving…' : 'Save Settings'}
          </button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Salt Allowlist sub-section (self-contained, reads/saves via main settings API)
// ---------------------------------------------------------------------------

const LOCKED_SALT_FUNCTIONS = new Set(['test.ping', 'grains.items', 'grains.get'])

function SaltAllowlistSection() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [functions, setFunctions] = useState<string[]>([])
  const [newFn, setNewFn] = useState('')
  const [dirty, setDirty] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: ansibleApi.getSettings,
  })

  useEffect(() => {
    if (data?.salt_allowed_functions) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- loading allowlist from server settings on data change; refactor tracked in #380 follow-up
      setFunctions(data.salt_allowed_functions)
      setDirty(false)
    }
  }, [data])

  const saveMutation = useMutation({
    mutationFn: () => ansibleApi.updateSettings({ salt_allowed_functions: functions }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      toast('Salt allowlist saved')
      setDirty(false)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function addFunction() {
    const trimmed = newFn.trim()
    if (!trimmed) return
    if (functions.includes(trimmed)) {
      toast(`'${trimmed}' is already in the allowlist`, 'error')
      return
    }
    const updated = [...functions, trimmed].sort()
    setFunctions(updated)
    setNewFn('')
    setDirty(true)
  }

  function removeFunction(fn: string) {
    if (LOCKED_SALT_FUNCTIONS.has(fn)) return
    setFunctions(functions.filter(f => f !== fn))
    setDirty(true)
  }

  if (isLoading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
        <div className="h-4 bg-gray-100 rounded animate-pulse w-48 mb-4" />
        <div className="h-3 bg-gray-100 rounded animate-pulse w-64" />
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-4">
      <div>
        <h2 className="text-base font-semibold text-gray-900">Salt Function Allowlist</h2>
        <p className="text-sm text-gray-500 mt-1">
          Only functions listed here can be dispatched via the ad-hoc Salt command API.
          Locked functions (shown with a lock badge) are always enforced and cannot be removed.
        </p>
      </div>

      {/* Chip list */}
      <div className="flex flex-wrap gap-2">
        {functions.map(fn => {
          const locked = LOCKED_SALT_FUNCTIONS.has(fn)
          return (
            <span
              key={fn}
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-mono font-medium border ${
                locked
                  ? 'bg-blue-50 border-blue-200 text-blue-800'
                  : 'bg-gray-50 border-gray-200 text-gray-700'
              }`}
            >
              {locked && (
                <svg width="10" height="10" viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
                  <rect x="2" y="5" width="8" height="6" rx="1" fill="currentColor" opacity="0.6"/>
                  <path d="M4 5V3.5a2 2 0 0 1 4 0V5" stroke="currentColor" strokeWidth="1.2" fill="none"/>
                </svg>
              )}
              {fn}
              {!locked && (
                <button
                  onClick={() => removeFunction(fn)}
                  aria-label={`Remove ${fn}`}
                  className="ml-0.5 text-gray-400 hover:text-red-600 transition-colors leading-none"
                >
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="flex-shrink-0">
                    <path d="M2 2l6 6M8 2L2 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                </button>
              )}
            </span>
          )
        })}
        {functions.length === 0 && (
          <p className="text-sm text-gray-400 italic">No functions configured — locked defaults will still apply.</p>
        )}
      </div>

      {/* Add new function input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={newFn}
          onChange={(e) => setNewFn(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addFunction() } }}
          placeholder="e.g. file.managed"
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono text-gray-900 focus:outline-none focus:border-brand-600"
        />
        <button
          onClick={addFunction}
          disabled={!newFn.trim()}
          className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 disabled:opacity-40 border border-gray-200"
        >
          Add
        </button>
      </div>

      {/* Save button */}
      <div className="flex items-center gap-3 pt-1">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending || !dirty}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50"
        >
          {saveMutation.isPending ? 'Saving…' : 'Save Allowlist'}
        </button>
        {dirty && (
          <span className="text-xs text-amber-600 font-medium">Unsaved changes</span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Salt Denylist sub-section (self-contained, reads/saves via main settings API)
// ---------------------------------------------------------------------------

function SaltDenylistSection() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [functions, setFunctions] = useState<string[]>([])
  const [newFn, setNewFn] = useState('')
  const [dirty, setDirty] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: ansibleApi.getSettings,
  })

  useEffect(() => {
    if (data) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- loading denylist from server settings on data change; refactor tracked in #380 follow-up
      setFunctions(data.salt_denied_functions ?? [])
      setDirty(false)
    }
  }, [data])

  const saveMutation = useMutation({
    mutationFn: () => ansibleApi.updateSettings({ salt_denied_functions: functions }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      toast('Salt denylist saved')
      setDirty(false)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  function addFunction() {
    const trimmed = newFn.trim()
    if (!trimmed) return
    if (functions.includes(trimmed)) {
      toast(`'${trimmed}' is already in the denylist`, 'error')
      return
    }
    const updated = [...functions, trimmed].sort()
    setFunctions(updated)
    setNewFn('')
    setDirty(true)
  }

  function removeFunction(fn: string) {
    setFunctions(functions.filter(f => f !== fn))
    setDirty(true)
  }

  if (isLoading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
        <div className="h-4 bg-gray-100 rounded animate-pulse w-48 mb-4" />
        <div className="h-3 bg-gray-100 rounded animate-pulse w-64" />
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-red-100 shadow-sm p-6 space-y-4">
      <div>
        <h2 className="text-base font-semibold text-gray-900">Salt Function Deny List</h2>
        <p className="text-sm text-gray-500 mt-1">
          Functions listed here are <span className="font-semibold text-red-700">always blocked</span>,
          even if they appear on the allow list. Use this to prevent specific functions from ever being
          called regardless of the allowlist configuration.
        </p>
      </div>

      {/* Chip list */}
      <div className="flex flex-wrap gap-2">
        {functions.map(fn => (
          <span
            key={fn}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-mono font-medium border bg-red-50 text-red-700 border-red-200"
          >
            {fn}
            <button
              onClick={() => removeFunction(fn)}
              aria-label={`Remove ${fn} from denylist`}
              className="ml-0.5 text-red-400 hover:text-red-700 transition-colors leading-none"
            >
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="flex-shrink-0">
                <path d="M2 2l6 6M8 2L2 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </button>
          </span>
        ))}
        {functions.length === 0 && (
          <p className="text-sm text-gray-400 italic">No functions denied — all allowlisted functions can be called.</p>
        )}
      </div>

      {/* Add new function input */}
      <div className="flex gap-2">
        <input
          type="text"
          value={newFn}
          onChange={(e) => setNewFn(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addFunction() } }}
          placeholder="e.g. system.reboot"
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono text-gray-900 focus:outline-none focus:border-red-400"
        />
        <button
          onClick={addFunction}
          disabled={!newFn.trim()}
          className="px-4 py-2 bg-red-50 text-red-700 rounded-lg text-sm font-medium hover:bg-red-100 disabled:opacity-40 border border-red-200"
        >
          Add
        </button>
      </div>

      {/* Save button */}
      <div className="flex items-center gap-3 pt-1">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending || !dirty}
          className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
        >
          {saveMutation.isPending ? 'Saving…' : 'Save Deny List'}
        </button>
        {dirty && (
          <span className="text-xs text-amber-600 font-medium">Unsaved changes</span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Credentials sub-section (self-contained, uses its own queries)
// ---------------------------------------------------------------------------

function KindBadge({ kind }: { kind: string }) {
  if (kind === 'token') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
        token
      </span>
    )
  }
  if (kind === 'ssh_key') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
        ssh key
      </span>
    )
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600">
      {kind}
    </span>
  )
}

function CredentialsSection() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const [showAddForm, setShowAddForm] = useState(false)
  const [credName, setCredName] = useState('')
  const [credKind, setCredKind] = useState<'token' | 'ssh_key'>('token')
  const [credSecret, setCredSecret] = useState('')
  const [credDescription, setCredDescription] = useState('')

  const { data: credentials = [], isLoading } = useQuery({
    queryKey: ['credentials'],
    queryFn: credentialsApi.list,
  })

  const createMutation = useMutation({
    mutationFn: credentialsApi.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['credentials'] })
      toast('Credential saved')
      setCredName('')
      setCredKind('token')
      setCredSecret('')
      setCredDescription('')
      setShowAddForm(false)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const removeMutation = useMutation({
    mutationFn: credentialsApi.remove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['credentials'] })
      toast('Credential deleted')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const inputClass = 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600'
  const btnPrimary = 'px-4 py-2 bg-brand-600 text-white text-sm rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50'
  const btnSecondary = 'px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm rounded-lg font-medium hover:bg-gray-50 disabled:opacity-50'

  return (
    <div id="credentials-section" className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">
      <div>
        <h2 className="text-base font-semibold text-gray-900">Credentials</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          Reusable credentials for private git repositories — referenced by name, secrets never leave the server.
        </p>
      </div>

      {/* Existing credentials list */}
      {isLoading ? (
        <Skeleton rows={2} />
      ) : (credentials as Credential[]).length === 0 ? (
        <p className="text-sm text-gray-400">No credentials configured.</p>
      ) : (
        <div className="space-y-2">
          {(credentials as Credential[]).map((cred) => (
            <div key={cred.id} className="flex items-center gap-3 px-3 py-2.5 border border-gray-200 rounded-lg">
              <KindBadge kind={cred.kind} />
              <div className="flex-1 min-w-0">
                <span className="text-sm font-medium text-gray-900">{cred.name}</span>
                {cred.description && (
                  <span className="ml-2 text-xs text-gray-500">{cred.description}</span>
                )}
              </div>
              {cred.last_used_at ? (
                <span className="text-xs text-gray-400 shrink-0">
                  last used {new Date(cred.last_used_at).toLocaleString('en-IN', {
                    timeZone: 'Asia/Kolkata',
                    day: '2-digit', month: 'short', year: 'numeric',
                  })} IST
                </span>
              ) : (
                <span className="text-xs text-gray-300 shrink-0">never used</span>
              )}
              <button
                onClick={() => removeMutation.mutate(cred.id)}
                disabled={removeMutation.isPending}
                title="Delete credential"
                className="text-gray-400 hover:text-red-500 transition-colors text-lg leading-none shrink-0"
              >×</button>
            </div>
          ))}
        </div>
      )}

      {/* Add credential inline form */}
      {!showAddForm ? (
        <button
          onClick={() => setShowAddForm(true)}
          className="text-sm text-brand-600 hover:text-brand-700 font-medium"
        >
          + Add credential
        </button>
      ) : (
        <div className="border border-gray-200 rounded-xl p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-700">New credential</p>

          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
            <input
              type="text"
              value={credName}
              onChange={(e) => setCredName(e.target.value)}
              placeholder="e.g. GitHub (personal)"
              className={inputClass}
            />
          </div>

          {/* Kind toggle */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setCredKind('token')}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                  credKind === 'token'
                    ? 'bg-brand-600 text-white border-brand-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                Personal access token
              </button>
              <button
                type="button"
                onClick={() => setCredKind('ssh_key')}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                  credKind === 'ssh_key'
                    ? 'bg-brand-600 text-white border-brand-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                }`}
              >
                SSH private key
              </button>
            </div>
          </div>

          {/* Secret input */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              {credKind === 'token' ? 'Token' : 'Private key'}
            </label>
            {credKind === 'token' ? (
              <SecretInput
                value={credSecret}
                onChange={setCredSecret}
                placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                className={inputClass}
              />
            ) : (
              <textarea
                value={credSecret}
                onChange={(e) => setCredSecret(e.target.value)}
                placeholder={"-----BEGIN OPENSSH PRIVATE KEY-----\n(paste SSH private key)"}
                rows={5}
                className={inputClass + ' font-mono'}
              />
            )}
          </div>

          {/* Optional description */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Description (optional)</label>
            <input
              type="text"
              value={credDescription}
              onChange={(e) => setCredDescription(e.target.value)}
              placeholder="e.g. Read-only access to org/ansible-playbooks"
              className={inputClass}
            />
          </div>

          <div className="flex gap-2 justify-end">
            <button
              onClick={() => {
                setShowAddForm(false)
                setCredName('')
                setCredKind('token')
                setCredSecret('')
                setCredDescription('')
              }}
              className={btnSecondary}
            >
              Cancel
            </button>
            <button
              onClick={() => createMutation.mutate({
                name: credName.trim(),
                kind: credKind,
                secret: credSecret.trim(),
                description: credDescription.trim() || undefined,
              })}
              disabled={!credName.trim() || !credSecret.trim() || createMutation.isPending}
              className={btnPrimary}
            >
              {createMutation.isPending ? 'Saving…' : 'Save Credential'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Playbook Sources sub-section (self-contained, uses its own queries)
// ---------------------------------------------------------------------------

function SourceTypeBadge({ type }: { type: string }) {
  if (type === 'git') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
        git
      </span>
    )
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
      local
    </span>
  )
}

type ValidateState = { status: 'idle' } | { status: 'validating' } | { status: 'valid'; result: PlaybookSourceValidateResponse } | { status: 'invalid'; error: string; logs?: string[]; authRequired?: boolean }

function ValidationResult({ v }: { v: ValidateState }) {
  if (v.status === 'idle') return null

  const logs: string[] = v.status === 'valid' ? (v.result.logs ?? []) : (v.status === 'invalid' ? (v.logs ?? []) : [])

  return (
    <div className="space-y-2">
      {/* Auth required amber callout — shown instead of terminal log when auth is the problem */}
      {v.status === 'invalid' && v.authRequired ? (
        <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg p-3">
          <span className="text-base leading-none shrink-0">🔐</span>
          <p className="text-sm text-amber-800">
            This repository is private or requires authentication — select or create a credential above, then validate again.
          </p>
        </div>
      ) : (
        /* Terminal log panel */
        <div className="bg-gray-950 rounded-lg p-3 font-mono text-xs space-y-0.5 max-h-48 overflow-y-auto">
          {v.status === 'validating' && (
            <p className="text-gray-400 animate-pulse">⏳ Connecting…</p>
          )}
          {v.status !== 'validating' && logs.map((line, i) => (
            <p key={i} className={
              line.includes('✓') ? 'text-green-400' :
              line.includes('✗') || line.includes('Error') ? 'text-red-400' :
              line.includes('⚠') ? 'text-amber-400' :
              'text-gray-300'
            }>{line}</p>
          ))}
          {v.status === 'valid' && (
            <p className="text-green-400 font-semibold mt-1">
              ✓ Ready to add — {v.result.playbook_count} playbooks, {v.result.role_count} roles
            </p>
          )}
          {v.status === 'invalid' && (
            <p className="text-red-400 font-semibold mt-1">✗ {v.error}</p>
          )}
        </div>
      )}
      {/* Entry badges for valid state */}
      {v.status === 'valid' && v.result.entries.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {v.result.entries.map((e) => (
            <span key={e.filename} className={`text-xs px-2 py-0.5 rounded font-mono border ${
              e.entry_type === 'role'
                ? 'bg-purple-50 text-purple-700 border-purple-200'
                : 'bg-brand-50 text-brand-700 border-brand-200'
            }`}>
              {e.lint_errors?.length ? '⚠ ' : ''}{e.name}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function PlaybookSourcesSection() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const [showAddLocal, setShowAddLocal] = useState(false)
  const [localPath, setLocalPath] = useState('')
  const [localLabel, setLocalLabel] = useState('')

  const [showAddGit, setShowAddGit] = useState(false)
  const [gitUrl, setGitUrl] = useState('')
  const [gitBranch, setGitBranch] = useState('main')
  const [gitLabel, setGitLabel] = useState('')
  const [gitCredentialId, setGitCredentialId] = useState<string>('')

  const [showCsv, setShowCsv] = useState(false)
  const [csvText, setCsvText] = useState('')
  const [lastAddType, setLastAddType] = useState<'local' | 'git'>('local')

  const [localValidation, setLocalValidation] = useState<ValidateState>({ status: 'idle' })
  const [gitValidation, setGitValidation] = useState<ValidateState>({ status: 'idle' })

  const { data: sources = [], isLoading } = useQuery({
    queryKey: ['playbook-sources'],
    queryFn: playbookSourcesApi.list,
  })

  const { data: credentials = [] } = useQuery({
    queryKey: ['credentials'],
    queryFn: credentialsApi.list,
  })

  const addMutation = useMutation({
    mutationFn: playbookSourcesApi.add,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playbook-sources'] })
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      toast(lastAddType === 'git'
        ? 'Git source added — click Sync to clone the repository and load playbooks'
        : 'Source added — playbooks refreshed')
      setLocalPath(''); setLocalLabel(''); setShowAddLocal(false); setLocalValidation({ status: 'idle' })
      setGitUrl(''); setGitBranch('main'); setGitLabel(''); setGitCredentialId(''); setShowAddGit(false); setGitValidation({ status: 'idle' })
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const removeMutation = useMutation({
    mutationFn: playbookSourcesApi.remove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playbook-sources'] })
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      toast('Source removed — playbooks hidden from list (files not deleted from disk)')
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const syncMutation = useMutation({
    mutationFn: playbookSourcesApi.sync,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      const ok = data.results.filter((r: { status?: string }) => r.status === 'ok').length
      const err = data.results.filter((r: { status?: string }) => r.status === 'error').length
      toast(err > 0 ? `Sync: ${ok} ok, ${err} failed` : `Synced ${ok} git source(s)`, err > 0 ? 'error' : undefined)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  const importMutation = useMutation({
    mutationFn: (csv: string) => playbookSourcesApi.importCsv(csv),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['playbook-sources'] })
      qc.invalidateQueries({ queryKey: ['playbooks'] })
      toast(`Imported ${data.added} source(s)`)
      setCsvText(''); setShowCsv(false)
    },
    onError: (e: Error) => toast(e.message, 'error'),
  })

  async function validateLocal() {
    if (!localPath.trim()) return
    setLocalValidation({ status: 'validating' })
    try {
      const result = await playbookSourcesApi.validate({ type: 'local', path: localPath.trim() })
      if (result.valid) {
        setLocalValidation({ status: 'valid', result })
      } else {
        setLocalValidation({ status: 'invalid', error: result.error ?? 'Validation failed', logs: result.logs })
      }
    } catch (e: unknown) {
      setLocalValidation({ status: 'invalid', error: (e instanceof Error ? e.message : null) ?? 'Validation error' })
    }
  }

  async function validateGit() {
    if (!gitUrl.trim()) return
    setGitValidation({ status: 'validating' })
    try {
      const result = await playbookSourcesApi.validate({
        type: 'git',
        url: gitUrl.trim(),
        branch: gitBranch || 'main',
        credential_id: gitCredentialId || undefined,
      })
      if (result.valid) {
        setGitValidation({ status: 'valid', result })
      } else {
        setGitValidation({ status: 'invalid', error: result.error ?? 'Validation failed', logs: result.logs, authRequired: !!result.auth_required })
      }
    } catch (e: unknown) {
      setGitValidation({ status: 'invalid', error: (e instanceof Error ? e.message : null) ?? 'Validation error' })
    }
  }

  const inputClass = 'flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600 font-mono'
  const btnPrimary = 'px-4 py-2 bg-brand-600 text-white text-sm rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50'
  const btnSecondary = 'px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm rounded-lg font-medium hover:bg-gray-50 disabled:opacity-50'

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Playbook Sources</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Additional directories and git repositories scanned for playbooks and roles.
            Each source is validated and scanned before being added.
          </p>
        </div>
        {(sources as PlaybookSource[]).some((s) => s.type === 'git') && (
          <button onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending} className={btnSecondary}>
            {syncMutation.isPending ? 'Syncing…' : 'Sync All Git'}
          </button>
        )}
      </div>

      {/* Built-in source */}
      <div className="flex items-center gap-3 px-3 py-2.5 bg-gray-50 border border-gray-200 rounded-lg">
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-200 text-gray-600">built-in</span>
        <span className="text-sm font-mono text-gray-700 flex-1">playbooks/</span>
        <span className="text-xs text-gray-400 italic">always active</span>
      </div>

      {/* Configured sources */}
      {isLoading ? (
        <Skeleton rows={3} />
      ) : (sources as PlaybookSource[]).length === 0 ? (
        <p className="text-sm text-gray-400">No additional sources configured.</p>
      ) : (
        <div className="space-y-2">
          {(sources as PlaybookSource[]).map((src, i) => (
            <div key={i} className="flex items-center gap-3 px-3 py-2.5 border border-gray-200 rounded-lg">
              <SourceTypeBadge type={src.type} />
              <span className="text-sm font-mono text-gray-700 flex-1 truncate">
                {src.label ? <span className="text-gray-900 font-medium mr-2">{src.label}</span> : null}
                {src.path ?? src.url}
                {src.branch && src.branch !== 'main' && <span className="ml-2 text-gray-400">@{src.branch}</span>}
              </span>
              <button
                onClick={() => removeMutation.mutate(i)}
                disabled={removeMutation.isPending}
                title="Remove source"
                className="text-gray-400 hover:text-red-500 transition-colors text-lg leading-none"
              >×</button>
            </div>
          ))}
        </div>
      )}

      {/* Add local directory */}
      <div className="space-y-2">
        {!showAddLocal ? (
          <button onClick={() => setShowAddLocal(true)} className="text-sm text-brand-600 hover:text-brand-700 font-medium">
            + Add local directory
          </button>
        ) : (
          <div className="border border-gray-200 rounded-xl p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-700">Add local directory</p>
            <div className="flex gap-2">
              <input
                type="text"
                value={localPath}
                onChange={(e) => { setLocalPath(e.target.value); setLocalValidation({ status: 'idle' }) }}
                placeholder="/path/to/playbooks"
                className={inputClass}
              />
              <button
                onClick={validateLocal}
                disabled={!localPath.trim() || localValidation.status === 'validating'}
                className={btnSecondary}
              >
                {localValidation.status === 'validating' ? 'Checking…' : 'Validate'}
              </button>
            </div>
            <input
              type="text"
              value={localLabel}
              onChange={(e) => setLocalLabel(e.target.value)}
              placeholder="Label (optional)"
              className={inputClass}
            />
            <ValidationResult v={localValidation} />
            <div className="flex gap-2 justify-end">
              <button onClick={() => { setShowAddLocal(false); setLocalPath(''); setLocalLabel(''); setLocalValidation({ status: 'idle' }) }} className={btnSecondary}>Cancel</button>
              <button
                onClick={() => { setLastAddType('local'); addMutation.mutate({ type: 'local', path: localPath.trim(), label: localLabel.trim() || undefined }) }}
                disabled={localValidation.status !== 'valid' || addMutation.isPending}
                className={btnPrimary}
              >
                {addMutation.isPending ? 'Adding…' : 'Add Source'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Add git repository */}
      <div className="space-y-2">
        {!showAddGit ? (
          <button onClick={() => setShowAddGit(true)} className="text-sm text-brand-600 hover:text-brand-700 font-medium">
            + Add git repository
          </button>
        ) : (
          <div className="border border-gray-200 rounded-xl p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-700">Add git repository</p>
            <div className="flex gap-2">
              <input
                type="text"
                value={gitUrl}
                onChange={(e) => { setGitUrl(e.target.value); setGitValidation({ status: 'idle' }) }}
                placeholder="https://github.com/org/ansible-playbooks.git"
                className={inputClass}
              />
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={gitBranch}
                onChange={(e) => { setGitBranch(e.target.value); setGitValidation({ status: 'idle' }) }}
                placeholder="Branch (default: main)"
                className={inputClass}
              />
              <button
                onClick={validateGit}
                disabled={!gitUrl.trim() || gitValidation.status === 'validating'}
                className={btnSecondary}
              >
                {gitValidation.status === 'validating' ? 'Checking…' : 'Validate & Clone'}
              </button>
            </div>
            <input
              type="text"
              value={gitLabel}
              onChange={(e) => setGitLabel(e.target.value)}
              placeholder="Label (optional)"
              className={inputClass}
            />
            {/* Credential dropdown */}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Credential (for private repositories)</label>
              <select
                value={gitCredentialId}
                onChange={(e) => {
                  const val = e.target.value
                  if (val === '__create_new__') {
                    // Scroll to CredentialsSection and open its form
                    const el = document.getElementById('credentials-section')
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
                    return
                  }
                  setGitCredentialId(val)
                  setGitValidation({ status: 'idle' })
                }}
                className={`w-full px-3 py-2 border rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600 ${
                  gitValidation.status === 'invalid' && gitValidation.authRequired && !gitCredentialId
                    ? 'border-amber-400 ring-2 ring-amber-200'
                    : 'border-gray-300'
                }`}
              >
                <option value="">— none (public repo) —</option>
                {(credentials as Credential[]).map((cred) => (
                  <option key={cred.id} value={cred.id}>
                    {cred.name} ({cred.kind === 'token' ? 'token' : 'ssh key'})
                  </option>
                ))}
                <option value="__create_new__">+ Create new credential…</option>
              </select>
            </div>
            <ValidationResult v={gitValidation} />
            <div className="flex gap-2 justify-end">
              <button onClick={() => { setShowAddGit(false); setGitUrl(''); setGitBranch('main'); setGitLabel(''); setGitCredentialId(''); setGitValidation({ status: 'idle' }) }} className={btnSecondary}>Cancel</button>
              <button
                onClick={() => { setLastAddType('git'); addMutation.mutate({
                  type: 'git',
                  url: gitUrl.trim(),
                  branch: gitBranch || 'main',
                  label: gitLabel.trim() || undefined,
                  credential_id: gitCredentialId || undefined,
                }) }}
                disabled={gitValidation.status !== 'valid' || addMutation.isPending}
                className={btnPrimary}
              >
                {addMutation.isPending ? 'Adding…' : 'Add Source'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* CSV import */}
      <div className="space-y-2">
        {!showCsv ? (
          <button onClick={() => setShowCsv(true)} className="text-sm text-gray-500 hover:text-gray-700 font-medium">
            + Import via CSV
          </button>
        ) : (
          <div className="border border-gray-200 rounded-xl p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-700">Import sources from CSV</p>
            <p className="text-xs text-gray-400">Format: <code>type,path_or_url,branch,label</code> — one per line. Branch and label are optional.</p>
            <textarea
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
              placeholder={`local,/path/to/playbooks,,My Playbooks\ngit,https://github.com/org/repo.git,main,Shared Roles`}
              className="w-full h-24 px-3 py-2 border border-gray-300 rounded-lg text-xs font-mono focus:outline-none focus:border-brand-600"
            />
            <p className="text-xs text-amber-600">⚠ CSV import validates sources but skips inaccessible ones rather than failing.</p>
            <div className="flex gap-2 justify-end">
              <button onClick={() => { setShowCsv(false); setCsvText('') }} className={btnSecondary}>Cancel</button>
              <button onClick={() => importMutation.mutate(csvText)} disabled={!csvText.trim() || importMutation.isPending} className={btnPrimary}>
                {importMutation.isPending ? 'Importing…' : 'Import'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// LLM Endpoints sub-section
// ---------------------------------------------------------------------------

function StatusPill({ result, checking }: {
  result?: { ok: boolean; latency_ms: number | null; error?: string | null }
  checking: boolean
}) {
  if (checking) return (
    <span className="inline-flex items-center gap-1 text-xs text-gray-400 whitespace-nowrap">
      <span className="animate-spin inline-block">⟳</span> Checking
    </span>
  )
  if (!result) return <span className="text-xs text-gray-300">—</span>
  if (result.ok) return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 whitespace-nowrap">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block flex-shrink-0" />
      {result.latency_ms != null ? `${result.latency_ms} ms` : 'OK'}
    </span>
  )
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-red-600 whitespace-nowrap">
      <span className="w-1.5 h-1.5 rounded-full bg-red-500 inline-block flex-shrink-0" />
      {result.error?.slice(0, 30) ?? 'Unreachable'}
    </span>
  )
}

function ProviderBadge({ provider }: { provider: string }) {
  if (provider === 'anthropic') {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-700">
        Anthropic
      </span>
    )
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
      OpenAI-compat
    </span>
  )
}

function LLMEndpointsSection() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)

  const [showForm, setShowForm] = useState(false)
  const [editingEndpoint, setEditingEndpoint] = useState<LLMEndpoint | undefined>(undefined)
  const [testingIds, setTestingIds] = useState<Set<string>>(new Set())
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [settingDefaultId, setSettingDefaultId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; latency_ms: number | null; error: string | null }>>({})

  const { data: endpoints = [], isLoading, isError } = useQuery({
    queryKey: ['llm-endpoints'],
    queryFn: llmApi.list,
  })

  // Auto-ping all endpoints when the list loads or changes size
  useEffect(() => {
    if (endpoints.length === 0) return
    endpoints.forEach(ep => handleTest(ep))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoints.length])

  const deleteMutation = useMutation({
    mutationFn: (id: string) => llmApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['llm-endpoints'] })
      toast('Endpoint deleted')
    },
    onError: (e: Error) => toast(e.message, 'error'),
    onSettled: () => setDeletingId(null),
  })

  function openAdd() {
    setEditingEndpoint(undefined)
    setShowForm(true)
  }

  function openEdit(ep: LLMEndpoint) {
    setEditingEndpoint(ep)
    setShowForm(true)
  }

  function handleSaved() {
    qc.invalidateQueries({ queryKey: ['llm-endpoints'] })
  }

  async function handleTest(ep: LLMEndpoint) {
    setTestingIds((prev) => new Set(prev).add(ep.id))
    setTestResults((prev) => {
      const next = { ...prev }
      delete next[ep.id]
      return next
    })
    try {
      const result = await llmApi.test(ep.id)
      setTestResults((prev) => ({ ...prev, [ep.id]: result }))
    } catch {
      setTestResults((prev) => ({ ...prev, [ep.id]: { ok: false, latency_ms: null, error: 'Unreachable' } }))
    } finally {
      setTestingIds((prev) => {
        const next = new Set(prev)
        next.delete(ep.id)
        return next
      })
    }
  }

  async function handleSetDefault(ep: LLMEndpoint) {
    if (ep.is_default) return
    setSettingDefaultId(ep.id)
    try {
      await llmApi.update(ep.id, { is_default: true })
      qc.invalidateQueries({ queryKey: ['llm-endpoints'] })
      toast(`${ep.name} set as default`)
    } catch (e: unknown) {
      toast((e instanceof Error ? e.message : null) ?? 'Failed to set default', 'error')
    } finally {
      setSettingDefaultId(null)
    }
  }

  function handleDelete(ep: LLMEndpoint) {
    if (!window.confirm(`Delete endpoint "${ep.name}"? This cannot be undone.`)) return
    setDeletingId(ep.id)
    deleteMutation.mutate(ep.id)
  }

  const btnSecondary = 'px-3 py-1.5 bg-white border border-gray-300 text-gray-700 text-xs rounded-lg font-medium hover:bg-gray-50 disabled:opacity-50'
  const btnDanger = 'px-3 py-1.5 bg-white border border-red-200 text-red-600 text-xs rounded-lg font-medium hover:bg-red-50 disabled:opacity-50'

  return (
    <>
      {showForm && (
        <LLMEndpointForm
          endpoint={editingEndpoint}
          onClose={() => { setShowForm(false); setEditingEndpoint(undefined) }}
          onSaved={handleSaved}
        />
      )}

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 space-y-5">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-900">LLM Endpoints</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Configure LLM providers for AI-assisted fleet operations. Supports Ollama, OpenAI-compatible endpoints, and Anthropic.
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {endpoints.length > 0 && (
              <button
                onClick={() => endpoints.forEach(ep => handleTest(ep))}
                className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1 font-medium"
                title="Re-ping all endpoints"
              >
                <span>↻</span> Refresh
              </button>
            )}
            <button
              onClick={openAdd}
              className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg font-medium hover:bg-brand-700 shadow-sm"
            >
              Add Endpoint
            </button>
          </div>
        </div>

        {isLoading && (
          <Skeleton rows={3} />
        )}

        {isError && (
          <div className="px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            Failed to load LLM endpoints. Check that the backend is running.
          </div>
        )}

        {!isLoading && !isError && endpoints.length === 0 && (
          <div className="text-center py-8 border border-dashed border-gray-200 rounded-lg">
            <p className="text-sm text-gray-500">No LLM endpoints configured.</p>
            <p className="text-xs text-gray-400 mt-1">Add an Ollama, OpenAI-compatible, or Anthropic endpoint to get started.</p>
          </div>
        )}

        {!isLoading && !isError && endpoints.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-600 uppercase tracking-wide">Name</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-600 uppercase tracking-wide">Provider</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-600 uppercase tracking-wide">Model</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-600 uppercase tracking-wide">Status</th>
                  <th className="text-center px-4 py-2.5 text-xs font-semibold text-gray-600 uppercase tracking-wide">Default</th>
                  <th className="text-center px-4 py-2.5 text-xs font-semibold text-gray-600 uppercase tracking-wide">Enabled</th>
                  <th className="text-center px-4 py-2.5 text-xs font-semibold text-gray-600 uppercase tracking-wide">Has Key</th>
                  <th className="text-right px-4 py-2.5 text-xs font-semibold text-gray-600 uppercase tracking-wide">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {endpoints.map((ep) => {
                  const testResult = testResults[ep.id]
                  const isChecking = testingIds.has(ep.id)
                  return (
                    <tr key={ep.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <span className="font-medium text-gray-900">{ep.name}</span>
                        {ep.base_url && (
                          <p className="text-xs font-mono text-gray-400 mt-0.5 truncate max-w-[180px]">{ep.base_url}</p>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <ProviderBadge provider={ep.provider} />
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-mono text-gray-700 text-xs">{ep.model}</span>
                      </td>
                      <td className="px-4 py-3">
                        <StatusPill result={testResult} checking={isChecking} />
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => handleSetDefault(ep)}
                          disabled={settingDefaultId === ep.id}
                          title={ep.is_default ? 'Default endpoint' : 'Set as default'}
                          className="w-5 h-5 rounded-full border-2 flex items-center justify-center mx-auto transition-colors hover:border-emerald-500 disabled:opacity-50"
                          style={{
                            borderColor: ep.is_default ? '#16a34a' : '#d1d5db',
                            backgroundColor: ep.is_default ? '#16a34a' : 'white',
                          }}
                        >
                          {ep.is_default && <span className="w-2 h-2 rounded-full bg-white block" />}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-center">
                        {ep.enabled ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-100 text-emerald-700">On</span>
                        ) : (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500">Off</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {ep.has_api_key ? (
                          <span className="text-emerald-600 text-xs font-medium">✓</span>
                        ) : (
                          <span className="text-gray-300 text-xs">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => openEdit(ep)}
                            disabled={deletingId === ep.id}
                            className={btnSecondary}
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => handleDelete(ep)}
                            disabled={deletingId === ep.id}
                            className={btnDanger}
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
