import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { formatDistanceToNow } from 'date-fns'
import {
  alertsApi,
  type AlertRule,
  type WebhookConfig,
  type CreateRuleBody,
  type CreateWebhookBody,
} from '../api/alerts'
import { Skeleton } from '../components/Skeleton'
import { ErrorState } from '../components/ErrorState'
import { useToastStore } from '../stores/toastStore'
import { ConfirmDialog } from '../components/ConfirmDialog'

const EVENT_TYPES = [
  { value: 'node_offline', label: 'Node Offline' },
  { value: 'drift_threshold', label: 'Drift Threshold' },
  { value: 'cve_found', label: 'CVE Found' },
  { value: 'key_pending', label: 'Key Pending' },
]

function eventIcon(type: string) {
  switch (type) {
    case 'node_offline': return '🔴'
    case 'drift_threshold': return '📊'
    case 'cve_found': return '🛡️'
    case 'key_pending': return '🔑'
    default: return '🔔'
  }
}

function eventLabel(type: string) {
  return EVENT_TYPES.find(e => e.value === type)?.label ?? type
}

// ── Recent Events ─────────────────────────────────────────────────────

function RecentEvents() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['alert-events'],
    queryFn: () => alertsApi.listEvents(50),
    refetchInterval: 30_000,
  })

  return (
    <section>
      <h2 className="text-lg font-semibold text-gray-800 mb-3">Recent Events</h2>
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? (
          <Skeleton rows={6} />
        ) : isError ? (
          <ErrorState message="Failed to load alert events" retry={refetch} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Message</th>
                <th className="px-4 py-3">Node</th>
                <th className="px-4 py-3">Fired</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">
                    No alert events yet
                  </td>
                </tr>
              )}
              {data?.items.map((e) => (
                <tr key={e.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 whitespace-nowrap">
                    <span className="text-base">{eventIcon(e.rule_id ?? '')}</span>
                  </td>
                  <td className="px-4 py-3 text-gray-700 max-w-md truncate">{e.message}</td>
                  <td className="px-4 py-3">
                    {e.node_id ? (
                      <Link
                        to={`/nodes/${e.node_id}`}
                        className="text-brand-600 hover:underline font-mono text-xs"
                      >
                        {e.node_id.slice(0, 8)}
                      </Link>
                    ) : (
                      <span className="text-gray-400 text-xs">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">
                    {e.fired_at
                      ? formatDistanceToNow(new Date(e.fired_at), { addSuffix: true })
                      : '—'}
                  </td>
                  <td className="px-4 py-3">
                    {e.delivered ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-100 text-green-700 text-xs font-medium">
                        Delivered
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 text-xs font-medium">
                        Pending
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}

// ── Alert Rules ───────────────────────────────────────────────────────

function AlertRules() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<CreateRuleBody>({
    name: '',
    event_type: 'node_offline',
    threshold: null,
    enabled: true,
  })

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['alert-rules'],
    queryFn: alertsApi.listRules,
  })

  const createMut = useMutation({
    mutationFn: alertsApi.createRule,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alert-rules'] })
      setShowForm(false)
      setForm({ name: '', event_type: 'node_offline', threshold: null, enabled: true })
      toast('Alert rule created', 'success')
    },
    onError: (err: Error) => toast(err.message, 'error'),
  })

  const deleteMut = useMutation({
    mutationFn: alertsApi.deleteRule,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alert-rules'] })
      toast('Alert rule deleted', 'success')
    },
    onError: (err: Error) => toast(err.message, 'error'),
  })

  const [deletingRule, setDeletingRule] = useState<AlertRule | null>(null)

  const needsThreshold = form.event_type === 'drift_threshold' || form.event_type === 'cve_found'

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold text-gray-800">Alert Rules</h2>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
        >
          {showForm ? 'Cancel' : '+ Add Rule'}
        </button>
      </div>

      {showForm && (
        <div className="mb-4 p-4 bg-gray-50 rounded-lg border border-gray-200 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. Offline Node Alert"
                className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Event Type</label>
              <select
                value={form.event_type}
                onChange={(e) => setForm({ ...form, event_type: e.target.value, threshold: null })}
                className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
              >
                {EVENT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
          </div>
          {needsThreshold && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Threshold{form.event_type === 'cve_found' ? ' (1=CRITICAL only, 2=HIGH+)' : ' (drift score)'}
              </label>
              <input
                type="number"
                value={form.threshold ?? ''}
                onChange={(e) => setForm({ ...form, threshold: e.target.value ? Number(e.target.value) : null })}
                className="w-32 px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
          )}
          <div className="flex items-center gap-2">
            <input
              id="rule-enabled"
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              className="rounded border-gray-300"
            />
            <label htmlFor="rule-enabled" className="text-sm text-gray-700">Enabled</label>
          </div>
          <button
            disabled={!form.name || createMut.isPending}
            onClick={() => createMut.mutate(form)}
            className="px-4 py-1.5 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-50 transition-colors"
          >
            {createMut.isPending ? 'Creating…' : 'Create Rule'}
          </button>
        </div>
      )}

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? (
          <Skeleton rows={4} />
        ) : isError ? (
          <ErrorState message="Failed to load alert rules" retry={refetch} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Threshold</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">
                    No alert rules configured
                  </td>
                </tr>
              )}
              {data?.items.map((rule: AlertRule) => (
                <tr key={rule.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-800">{rule.name}</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1.5 text-gray-700">
                      <span>{eventIcon(rule.event_type)}</span>
                      <span>{eventLabel(rule.event_type)}</span>
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {rule.threshold != null ? rule.threshold : <span className="text-gray-400">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    {rule.enabled ? (
                      <span className="px-2 py-0.5 rounded-full bg-green-100 text-green-700 text-xs font-medium">Enabled</span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 text-xs font-medium">Disabled</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setDeletingRule(rule)}
                      className="text-red-500 hover:text-red-700 text-xs font-medium"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {deletingRule && (
        <ConfirmDialog
          title={`Delete rule "${deletingRule.name}"?`}
          message="This alert rule will be permanently removed."
          confirmLabel="Delete"
          destructive
          onConfirm={() => { deleteMut.mutate(deletingRule.id); setDeletingRule(null) }}
          onCancel={() => setDeletingRule(null)}
        />
      )}
    </section>
  )
}

// ── Webhook Targets ───────────────────────────────────────────────────

function WebhookTargets() {
  const qc = useQueryClient()
  const toast = useToastStore((s) => s.add)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<CreateWebhookBody>({
    name: '',
    url: '',
    type: 'slack',
    enabled: true,
  })
  const [deletingWebhook, setDeletingWebhook] = useState<WebhookConfig | null>(null)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['alert-webhooks'],
    queryFn: alertsApi.listWebhooks,
  })

  const createMut = useMutation({
    mutationFn: alertsApi.createWebhook,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alert-webhooks'] })
      setShowForm(false)
      setForm({ name: '', url: '', type: 'slack', enabled: true })
      toast('Webhook created', 'success')
    },
    onError: (err: Error) => toast(err.message, 'error'),
  })

  const deleteMut = useMutation({
    mutationFn: alertsApi.deleteWebhook,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['alert-webhooks'] })
      toast('Webhook deleted', 'success')
    },
    onError: (err: Error) => toast(err.message, 'error'),
  })

  const testMut = useMutation({
    mutationFn: alertsApi.testWebhook,
    onSuccess: () => toast('Test payload delivered successfully', 'success'),
    onError: (err: Error) => toast(`Test failed: ${err.message}`, 'error'),
  })

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold text-gray-800">Webhook Targets</h2>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="px-3 py-1.5 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
        >
          {showForm ? 'Cancel' : '+ Add Webhook'}
        </button>
      </div>

      {showForm && (
        <div className="mb-4 p-4 bg-gray-50 rounded-lg border border-gray-200 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. Slack #alerts"
                className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
              <select
                value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value as 'slack' | 'generic' })}
                className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
              >
                <option value="slack">Slack</option>
                <option value="generic">Generic (JSON)</option>
              </select>
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Webhook URL</label>
            <input
              type="url"
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
              placeholder="https://hooks.slack.com/services/…"
              className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              id="wh-enabled"
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              className="rounded border-gray-300"
            />
            <label htmlFor="wh-enabled" className="text-sm text-gray-700">Enabled</label>
          </div>
          <button
            disabled={!form.name || !form.url || createMut.isPending}
            onClick={() => createMut.mutate(form)}
            className="px-4 py-1.5 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-50 transition-colors"
          >
            {createMut.isPending ? 'Creating…' : 'Create Webhook'}
          </button>
        </div>
      )}

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        {isLoading ? (
          <Skeleton rows={4} />
        ) : isError ? (
          <ErrorState message="Failed to load webhooks" retry={refetch} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">URL</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">
                    No webhooks configured
                  </td>
                </tr>
              )}
              {data?.items.map((wh: WebhookConfig) => (
                <tr key={wh.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-800">{wh.name}</td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-600 max-w-[220px] truncate">
                    {wh.url}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      wh.type === 'slack' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                    }`}>
                      {wh.type === 'slack' ? 'Slack' : 'Generic'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {wh.enabled ? (
                      <span className="px-2 py-0.5 rounded-full bg-green-100 text-green-700 text-xs font-medium">Enabled</span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 text-xs font-medium">Disabled</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 justify-end">
                      <button
                        onClick={() => testMut.mutate(wh.id)}
                        disabled={testMut.isPending}
                        className="text-brand-600 hover:text-brand-800 text-xs font-medium disabled:opacity-50"
                      >
                        Test
                      </button>
                      <button
                        onClick={() => setDeletingWebhook(wh)}
                        className="text-red-500 hover:text-red-700 text-xs font-medium"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {deletingWebhook && (
        <ConfirmDialog
          title={`Delete webhook "${deletingWebhook.name}"?`}
          message="This webhook target will be permanently removed."
          confirmLabel="Delete"
          destructive
          onConfirm={() => { deleteMut.mutate(deletingWebhook.id); setDeletingWebhook(null) }}
          onCancel={() => setDeletingWebhook(null)}
        />
      )}
    </section>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────

export function AlertsPage() {
  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-gray-900">Alerts & Webhooks</h1>
      <RecentEvents />
      <AlertRules />
      <WebhookTargets />
    </div>
  )
}
