import { useState, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { llmApi, type LLMEndpoint, type LLMEndpointCreate, type LLMProvider } from '../api/llm'
import { useToastStore } from '../stores/toastStore'

interface Props {
  endpoint?: LLMEndpoint
  onClose: () => void
  onSaved: () => void
}

const PROVIDERS: { value: LLMProvider; label: string; needsUrl: boolean; defaultKey: string }[] = [
  { value: 'ollama',        label: 'Ollama (local)',                  needsUrl: true,  defaultKey: 'dummy' },
  { value: 'vllm',          label: 'vLLM',                            needsUrl: true,  defaultKey: 'dummy' },
  { value: 'llamacpp',      label: 'llama.cpp (server)',              needsUrl: true,  defaultKey: 'dummy' },
  { value: 'openai_compat', label: 'OpenAI-compatible (generic)',     needsUrl: true,  defaultKey: '' },
  { value: 'anthropic',     label: 'Anthropic',                       needsUrl: false, defaultKey: '' },
]

export function LLMEndpointForm({ endpoint, onClose, onSaved }: Props) {
  const isEdit = !!endpoint
  const toast = useToastStore((s) => s.add)

  const [name, setName] = useState(endpoint?.name ?? '')
  const [provider, setProvider] = useState<LLMProvider>(endpoint?.provider ?? 'ollama')
  const [baseUrl, setBaseUrl] = useState(endpoint?.base_url ?? '')
  const [model, setModel] = useState(endpoint?.model ?? '')
  const [maxTokens, setMaxTokens] = useState(String(endpoint?.max_tokens ?? 4096))
  const [apiKey, setApiKey] = useState('')
  const [isDefault, setIsDefault] = useState(endpoint?.is_default ?? false)
  const [enabled, setEnabled] = useState(endpoint?.enabled ?? true)
  const [formError, setFormError] = useState<string | null>(null)

  const [discoveredModels, setDiscoveredModels] = useState<Array<{ id: string; name: string }>>([])
  const [discovering, setDiscovering] = useState(false)
  const [discoveryError, setDiscoveryError] = useState<string | null>(null)

  // Reset form when endpoint prop changes (edit-mode) or clears (add-mode)
  useEffect(() => {
    if (endpoint) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- syncing all form fields from the endpoint prop on prop change; refactor tracked in #380 follow-up
      setName(endpoint.name)
      setProvider(endpoint.provider)
      setBaseUrl(endpoint.base_url ?? '')
      setModel(endpoint.model)
      setMaxTokens(String(endpoint.max_tokens))
      setIsDefault(endpoint.is_default)
      setEnabled(endpoint.enabled)
      setApiKey('') // never pre-populate; "leave blank to keep existing"
    } else {
      // reset to defaults for add-mode
      setName('')
      setProvider('ollama')
      setBaseUrl('')
      setModel('')
      setMaxTokens('4096')
      setIsDefault(false)
      setEnabled(true)
      setApiKey('')
    }
  }, [endpoint])

  // Auto-fill API key when provider changes (add mode only)
  useEffect(() => {
    const p = PROVIDERS.find((p) => p.value === provider)
    if (p?.defaultKey && !isEdit) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- auto-populating default API key when provider changes; refactor tracked in #380 follow-up
      setApiKey(p.defaultKey)
    }
  }, [provider]) // eslint-disable-line react-hooks/exhaustive-deps

  // Reset discovered models when provider changes
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting derived model list on provider change; refactor tracked in #380 follow-up
    setDiscoveredModels([])
    setDiscoveryError(null)
  }, [provider])

  // Auto-discover models on URL change (debounced 600ms)
  useEffect(() => {
    if (!baseUrl.trim() || provider === 'anthropic') {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clearing stale model list when URL is blank or provider is Anthropic; refactor tracked in #380 follow-up
      setDiscoveredModels([])
      return
    }
    const t = setTimeout(async () => {
      setDiscovering(true)
      setDiscoveryError(null)
      try {
        const res = await llmApi.discoverModels(baseUrl.trim(), provider)
        setDiscoveredModels(res.models)
        if (res.models.length > 0 && !model) {
          setModel(res.models[0].id)
        }
      } catch {
        setDiscoveryError('Could not reach endpoint')
        setDiscoveredModels([])
      } finally {
        setDiscovering(false)
      }
    }, 600)
    return () => clearTimeout(t)
  }, [baseUrl, provider]) // eslint-disable-line react-hooks/exhaustive-deps

  const mutation = useMutation({
    mutationFn: () => {
      const payload: LLMEndpointCreate = {
        name: name.trim(),
        provider,
        base_url: provider !== 'anthropic' ? (baseUrl.trim() || null) : null,
        model: model.trim(),
        max_tokens: parseInt(maxTokens, 10) || 4096,
        is_default: isDefault,
        enabled,
        api_key: apiKey.trim() || null,
      }
      if (isEdit) {
        return llmApi.update(endpoint!.id, payload)
      }
      return llmApi.create(payload)
    },
    onSuccess: () => {
      toast(isEdit ? 'Endpoint updated' : 'Endpoint added')
      onSaved()
      onClose()
    },
    onError: (e: Error) => {
      setFormError(e.message)
    },
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    if (!name.trim()) { setFormError('Name is required.'); return }
    if (!model.trim()) { setFormError('Model is required.'); return }
    mutation.mutate()
  }

  const inputClass =
    'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-gray-900 focus:outline-none focus:border-brand-600'

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white rounded-xl border border-gray-200 shadow-xl w-full max-w-lg mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold text-gray-900">
            {isEdit ? 'Edit LLM Endpoint' : 'Add LLM Endpoint'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Local Ollama, vLLM GPU Server"
              className={inputClass}
              required
            />
          </div>

          {/* Provider */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Provider <span className="text-red-500">*</span>
            </label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value as LLMProvider)}
              className={inputClass}
              required
            >
              {PROVIDERS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>

          {/* Base URL — all providers except anthropic */}
          {provider !== 'anthropic' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Base URL</label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={
                  provider === 'ollama' ? 'http://localhost:11434' :
                  provider === 'vllm'   ? 'http://localhost:8000' :
                  provider === 'llamacpp' ? 'http://localhost:8080' :
                  'http://localhost:11434/v1'
                }
                className={inputClass + ' font-mono'}
              />
              <p className="text-xs text-gray-400 mt-1">
                {discovering
                  ? 'Querying endpoint for available models…'
                  : discoveredModels.length > 0
                    ? `${discoveredModels.length} model(s) discovered from this endpoint.`
                    : 'Enter URL to auto-discover available models.'}
              </p>
            </div>
          )}

          {/* Model */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1 flex items-center gap-2">
              Model <span className="text-red-500">*</span>
              {discovering && (
                <span className="text-xs text-brand-500 font-normal">Discovering…</span>
              )}
              {!discovering && discoveredModels.length > 0 && (
                <span className="text-xs text-emerald-600 font-normal">
                  &#10003; {discoveredModels.length} models found
                </span>
              )}
              {discoveryError && (
                <span className="text-xs text-amber-600 font-normal">&#9888; {discoveryError}</span>
              )}
            </label>
            {discoveredModels.length > 0 ? (
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className={inputClass + ' font-mono'}
                required
              >
                <option value="">Select a model…</option>
                {discoveredModels.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={
                  provider === 'anthropic' ? 'claude-sonnet-4-6' :
                  provider === 'ollama'    ? 'llama3.2' :
                  'model-id'
                }
                className={inputClass + ' font-mono'}
                required
              />
            )}
          </div>

          {/* Max tokens */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Max tokens</label>
            <input
              type="number"
              value={maxTokens}
              onChange={(e) => setMaxTokens(e.target.value)}
              min={1}
              max={200000}
              className={inputClass}
            />
          </div>

          {/* API key */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              API key
              <span className="ml-2 text-xs font-normal text-gray-400">(stored encrypted)</span>
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                isEdit && endpoint?.has_api_key
                  ? 'Leave blank to keep existing'
                  : provider === 'ollama' || provider === 'vllm' || provider === 'llamacpp'
                    ? 'Pre-filled: dummy (edit if needed)'
                    : 'Paste API key'
              }
              className={inputClass}
            />
          </div>

          {/* Checkboxes */}
          <div className="flex items-center gap-6 pt-1">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isDefault}
                onChange={(e) => setIsDefault(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-600"
              />
              <span className="text-sm text-gray-700">Set as default endpoint</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-600"
              />
              <span className="text-sm text-gray-700">Enabled</span>
            </label>
          </div>

          {/* Inline error */}
          {formError && (
            <div className="px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              {formError}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm rounded-lg font-medium hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg font-medium hover:bg-brand-700 disabled:opacity-50 shadow-sm"
            >
              {mutation.isPending ? 'Saving…' : isEdit ? 'Save Changes' : 'Add Endpoint'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
