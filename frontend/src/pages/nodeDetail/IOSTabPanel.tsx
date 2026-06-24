import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { differenceInDays, formatDistanceToNow, parseISO } from 'date-fns'

import { iosTrackingApi, type AddCertBody, type IOSNodeDetail } from '../../api/iosTracking'
import type { Node } from '../../types'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { CERT_TYPES } from './utils'

// IOSTabPanel is the heaviest non-overview tab on NodeDetail and is only ever
// rendered for macOS/iOS hosts. Splitting it into its own module lets
// React.lazy on the parent skip its bundle (~9 kB minified) until the iOS
// tab is actually selected (#arch-nodedetail).

function AddCertForm({
  nodeId,
  onClose,
  qc,
  toast,
}: {
  nodeId: string
  onClose: () => void
  qc: ReturnType<typeof useQueryClient>
  toast: (message: string, type?: 'success' | 'error' | 'info') => void
}) {
  const [form, setForm] = useState<AddCertBody>({
    name: '',
    cert_type: 'code_signing',
    team_id: '',
    expiry_date: '',
    fingerprint: '',
  })

  const mut = useMutation({
    mutationFn: () => iosTrackingApi.addCertificate(nodeId, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ios-node-detail', nodeId] })
      toast('Certificate added', 'success')
      onClose()
    },
    onError: (err: Error) => toast(err.message, 'error'),
  })

  return (
    <div className="p-4 bg-gray-50 border border-gray-200 rounded-lg space-y-3 mb-4">
      <h3 className="text-sm font-semibold text-gray-800">Add Certificate</h3>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
          <input type="text" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
          <select value={form.cert_type}
            onChange={(e) => setForm({ ...form, cert_type: e.target.value })}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500">
            {CERT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Team ID</label>
          <input type="text" value={form.team_id ?? ''}
            onChange={(e) => setForm({ ...form, team_id: e.target.value })}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Expiry Date</label>
          <input type="date" value={form.expiry_date}
            onChange={(e) => setForm({ ...form, expiry_date: e.target.value })}
            className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500" />
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Fingerprint (optional)</label>
        <input type="text" value={form.fingerprint ?? ''}
          onChange={(e) => setForm({ ...form, fingerprint: e.target.value })}
          className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 font-mono" />
      </div>
      <div className="flex gap-2">
        <button
          disabled={!form.name || !form.expiry_date || mut.isPending}
          onClick={() => mut.mutate()}
          className="px-4 py-1.5 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-50 transition-colors"
        >
          {mut.isPending ? 'Adding…' : 'Add Certificate'}
        </button>
        <button onClick={onClose}
          className="px-4 py-1.5 rounded-lg border border-gray-300 text-sm text-gray-600 hover:bg-gray-50 transition-colors">
          Cancel
        </button>
      </div>
    </div>
  )
}

export interface IOSTabPanelProps {
  node: Node
  nodeId: string
  iosDetail: IOSNodeDetail | null
  showAddCert: boolean
  setShowAddCert: (v: boolean) => void
  showJenkinsConfigure: boolean
  setShowJenkinsConfigure: (v: boolean) => void
  jenkinsForm: { jenkins_url: string; agent_name: string }
  setJenkinsForm: (v: { jenkins_url: string; agent_name: string }) => void
  checkingJenkins: boolean
  checkJenkinsNow: () => Promise<void>
  deleteCertMutation: { mutate: (certId: string) => void; isPending: boolean }
  upsertJenkinsMutation: {
    mutate: (body: { jenkins_url: string; agent_name: string }) => void
    isPending: boolean
  }
  qc: ReturnType<typeof useQueryClient>
  toast: (message: string, type?: 'success' | 'error' | 'info') => void
}

export default function IOSTabPanel({
  node,
  nodeId,
  iosDetail,
  showAddCert,
  setShowAddCert,
  showJenkinsConfigure,
  setShowJenkinsConfigure,
  jenkinsForm,
  setJenkinsForm,
  checkingJenkins,
  checkJenkinsNow,
  deleteCertMutation,
  upsertJenkinsMutation,
  qc,
  toast,
}: IOSTabPanelProps) {
  const [deletingCert, setDeletingCert] = useState<string | null>(null)
  const agent = iosDetail?.jenkins_agent ?? null
  const certs = iosDetail?.certificates ?? []

  return (
    <div className="space-y-4">
      {/* Build Environment card */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <h3 className="font-semibold text-gray-700 mb-3">Build Environment</h3>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-gray-500">macOS Version</dt>
            <dd className="font-medium font-mono">{node.macos_version ?? '—'}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">Xcode Version</dt>
            <dd className="font-medium font-mono">{node.xcode_version ?? '—'}</dd>
          </div>
        </dl>
      </div>

      {/* Jenkins Agent card */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-700">Jenkins Agent</h3>
          <div className="flex items-center gap-2">
            <button
              onClick={checkJenkinsNow}
              disabled={checkingJenkins || !agent}
              className="text-xs text-brand-600 hover:text-brand-800 font-medium disabled:opacity-40"
            >
              {checkingJenkins ? 'Checking…' : 'Check now'}
            </button>
            <button
              onClick={() => {
                setJenkinsForm({ jenkins_url: agent?.jenkins_url ?? '', agent_name: agent?.agent_name ?? '' })
                setShowJenkinsConfigure(!showJenkinsConfigure)
              }}
              className="text-xs text-gray-600 hover:text-gray-800 font-medium border border-gray-300 rounded px-2 py-1"
            >
              Configure
            </button>
          </div>
        </div>

        {showJenkinsConfigure && (
          <div className="p-4 bg-gray-50 border border-gray-200 rounded-lg space-y-3 mb-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Jenkins URL</label>
              <input type="url" value={jenkinsForm.jenkins_url}
                onChange={(e) => setJenkinsForm({ ...jenkinsForm, jenkins_url: e.target.value })}
                placeholder="https://jenkins.example.com"
                className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Agent Name</label>
              <input type="text" value={jenkinsForm.agent_name}
                onChange={(e) => setJenkinsForm({ ...jenkinsForm, agent_name: e.target.value })}
                placeholder="mac-mini-agent-01"
                className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500" />
            </div>
            <div className="flex gap-2">
              <button
                disabled={!jenkinsForm.jenkins_url || !jenkinsForm.agent_name || upsertJenkinsMutation.isPending}
                onClick={() => upsertJenkinsMutation.mutate(jenkinsForm)}
                className="px-4 py-1.5 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 disabled:opacity-50 transition-colors"
              >
                {upsertJenkinsMutation.isPending ? 'Saving…' : 'Save'}
              </button>
              <button onClick={() => setShowJenkinsConfigure(false)}
                className="px-4 py-1.5 rounded-lg border border-gray-300 text-sm text-gray-600 hover:bg-gray-50 transition-colors">
                Cancel
              </button>
            </div>
          </div>
        )}

        {agent ? (
          <dl className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <dt className="text-gray-500">Status</dt>
              <dd>
                <span className="inline-flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    agent.status === 'online' ? 'bg-green-500' : agent.status === 'offline' ? 'bg-red-500' : 'bg-gray-400'
                  }`} />
                  <span className="text-xs capitalize text-gray-700">{agent.status}</span>
                </span>
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">Jenkins URL</dt>
              <dd className="font-mono text-xs text-gray-700">{agent.jenkins_url}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">Agent Name</dt>
              <dd className="font-mono text-xs text-gray-700">{agent.agent_name}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500">Last Checked</dt>
              <dd className="text-xs text-gray-500">
                {agent.last_checked_at
                  ? formatDistanceToNow(new Date(agent.last_checked_at), { addSuffix: true })
                  : '—'}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-gray-600">No Jenkins agent configured. Click "Configure" to set one up.</p>
        )}
      </div>

      {/* Certificates card */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-700">Certificates</h3>
          <button
            onClick={() => setShowAddCert(!showAddCert)}
            className="text-xs text-brand-600 hover:text-brand-800 font-medium border border-brand-200 rounded px-2 py-1"
          >
            + Add cert
          </button>
        </div>

        {showAddCert && (
          <AddCertForm
            nodeId={nodeId}
            onClose={() => setShowAddCert(false)}
            qc={qc}
            toast={toast}
          />
        )}

        {certs.length === 0 ? (
          <p className="text-sm text-gray-600">No certificates tracked for this node.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-gray-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                  <th scope="col" className="px-4 py-3">Name</th>
                  <th scope="col" className="px-4 py-3">Type</th>
                  <th scope="col" className="px-4 py-3">Team ID</th>
                  <th scope="col" className="px-4 py-3">Expiry</th>
                  <th scope="col" className="px-4 py-3">Fingerprint</th>
                  <th scope="col" className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {certs.map((cert) => {
                  const d = differenceInDays(parseISO(cert.expiry_date), new Date())
                  const expiryClass = d < 0 ? 'text-red-700 font-semibold' : d < 30 ? 'text-red-600 font-medium' : d < 60 ? 'text-amber-600 font-medium' : 'text-gray-700'
                  return (
                    <tr key={cert.id} className="hover:bg-gray-50">
                      <td className="px-4 py-2 font-medium text-gray-800">{cert.name}</td>
                      <td className="px-4 py-2">
                        <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700 text-xs font-medium">
                          {cert.cert_type}
                        </span>
                      </td>
                      <td className="px-4 py-2 font-mono text-xs text-gray-600">{cert.team_id ?? '—'}</td>
                      <td className={`px-4 py-2 text-xs ${expiryClass}`}>
                        {cert.expiry_date}
                        {d < 60 && d >= 0 && <span className="ml-1">({d}d)</span>}
                        {d < 0 && <span className="ml-1">(expired)</span>}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs text-gray-500 max-w-[120px] truncate" title={cert.fingerprint ?? ''}>
                        {cert.fingerprint ? cert.fingerprint.slice(0, 16) + '…' : '—'}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <button
                          onClick={() => setDeletingCert(cert.id)}
                          disabled={deleteCertMutation.isPending}
                          className="text-xs text-red-500 hover:text-red-700 font-medium disabled:opacity-50"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {deletingCert && (
        <ConfirmDialog
          title="Delete this certificate?"
          message="This certificate will be permanently removed from the node."
          confirmLabel="Delete"
          destructive
          onConfirm={() => { deleteCertMutation.mutate(deletingCert); setDeletingCert(null) }}
          onCancel={() => setDeletingCert(null)}
        />
      )}
    </div>
  )
}
