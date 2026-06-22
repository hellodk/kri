import { useState, useRef, useEffect, useCallback } from 'react'
import { streamQuery } from '../api/llm'
import { streamAgent, type AgentEvent } from '../api/agent'
import { ToolStep, ToolResultCard, type ToolStepData } from './AgentToolStep'
import { useLLMStore } from '../stores/llmStore'

type AssistantMode = 'qa' | 'agent'

type AgentItem = { kind: 'step'; iteration: number } | { kind: 'tool'; step: ToolStepData }

interface AgentTurn {
  prompt: string
  model?: string
  items: AgentItem[]
  final?: string
  note?: string
  error?: string
  meta?: { iterations: number; tool_calls: number; tokens_in: number; tokens_out: number; duration_ms: number }
  running: boolean
}

function classifyIntentHint(prompt: string): string {
  const p = prompt.toLowerCase()
  if ((p.includes('write') || p.includes('generate')) && (p.includes('sls') || p.includes('salt state'))) return 'Salt State'
  if ((p.includes('write') || p.includes('generate')) && (p.includes('playbook') || p.includes('ansible'))) return 'Ansible Playbook'
  if (p.includes('run') || p.includes('execute')) return 'Fleet Command'
  if (p.startsWith('explain') || p.includes('what does') || p.includes('how does')) return 'Explain'
  return 'Fleet Query'
}

function loadPos(): { x: number; y: number } | null {
  try {
    const raw = localStorage.getItem('llm-assistant-pos')
    if (!raw) return null
    return JSON.parse(raw) as { x: number; y: number }
  } catch {
    return null
  }
}

export default function LLMAssistant() {
  const [open, setOpen] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [intentHint, setIntentHint] = useState('Fleet Query')
  const [pos, setPos] = useState<{ x: number; y: number } | null>(loadPos)
  const [streaming, setStreaming] = useState(false)
  const [mode, setMode] = useState<AssistantMode>('qa')
  const [agentTurns, setAgentTurns] = useState<AgentTurn[]>([])
  const { messages, addMessage, clearMessages, appendToLastMessage, patchLastMessage } = useLLMStore()
  const bottomRef = useRef<HTMLDivElement>(null)
  const intentDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const streamControllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    // If the user navigates away or unmounts the component while a stream
    // is in-flight, abort it so the upstream LLM call is cancelled rather
    // than leaking tokens.
    return () => streamControllerRef.current?.abort()
  }, [])

  // Drag state kept in refs to avoid re-renders during pointer move
  const draggingRef = useRef(false)
  const dragStartPointer = useRef({ x: 0, y: 0 })
  const dragStartElem = useRef({ x: 0, y: 0 })
  const dragElemSize = useRef({ w: 0, h: 0 })
  const movedDistanceRef = useRef(0)

  const panelRef = useRef<HTMLDivElement>(null)
  const iconRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, agentTurns])

  // Re-clamp pos into viewport on window resize
  useEffect(() => {
    const handleResize = () => {
      setPos(prev => {
        if (!prev) return prev
        const el = panelRef.current || iconRef.current
        const w = el ? el.offsetWidth : 384   // w-96 = 24rem = 384px
        const h = el ? el.offsetHeight : 56   // h-14 = 56px
        const nx = Math.max(0, Math.min(prev.x, window.innerWidth - w))
        const ny = Math.max(0, Math.min(prev.y, window.innerHeight - h))
        if (nx === prev.x && ny === prev.y) return prev
        const clamped = { x: nx, y: ny }
        localStorage.setItem('llm-assistant-pos', JSON.stringify(clamped))
        return clamped
      })
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  const startDrag = useCallback((e: React.PointerEvent<HTMLElement>, elemRef: React.RefObject<HTMLElement | null>) => {
    // Don't start drag on Close / Clear button clicks (they are children)
    if ((e.target as HTMLElement).closest('button') !== e.currentTarget) return

    const el = elemRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()

    draggingRef.current = true
    movedDistanceRef.current = 0
    dragStartPointer.current = { x: e.clientX, y: e.clientY }
    dragStartElem.current = { x: pos?.x ?? rect.left, y: pos?.y ?? rect.top }
    dragElemSize.current = { w: el.offsetWidth, h: el.offsetHeight }

    e.currentTarget.setPointerCapture(e.pointerId)
  }, [pos])

  const onPointerDownIcon = useCallback((e: React.PointerEvent<HTMLButtonElement>) => {
    startDrag(e, iconRef as React.RefObject<HTMLElement>)
  }, [startDrag])

  const onPointerDownHeader = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    // Don't initiate drag when clicking Close or Clear buttons
    const target = e.target as HTMLElement
    if (target.closest('button')) return
    const el = panelRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()

    draggingRef.current = true
    movedDistanceRef.current = 0
    dragStartPointer.current = { x: e.clientX, y: e.clientY }
    dragStartElem.current = { x: pos?.x ?? rect.left, y: pos?.y ?? rect.top }
    dragElemSize.current = { w: el.offsetWidth, h: el.offsetHeight }

    e.currentTarget.setPointerCapture(e.pointerId)
  }, [pos])

  const onPointerMove = useCallback((e: React.PointerEvent<HTMLElement>) => {
    if (!draggingRef.current) return
    const dx = e.clientX - dragStartPointer.current.x
    const dy = e.clientY - dragStartPointer.current.y
    movedDistanceRef.current = Math.sqrt(dx * dx + dy * dy)
    const { w, h } = dragElemSize.current
    const nx = Math.max(0, Math.min(dragStartElem.current.x + dx, window.innerWidth - w))
    const ny = Math.max(0, Math.min(dragStartElem.current.y + dy, window.innerHeight - h))
    setPos({ x: nx, y: ny })
  }, [])

  const onPointerUp = useCallback((_e: React.PointerEvent<HTMLElement>, isIcon?: boolean) => {
    if (!draggingRef.current) return
    draggingRef.current = false
    const moved = movedDistanceRef.current

    setPos(prev => {
      if (prev) localStorage.setItem('llm-assistant-pos', JSON.stringify(prev))
      return prev
    })

    // Click-vs-drag: if total movement < 5px and it was the closed icon, open the panel
    if (isIcon && moved < 5) {
      setOpen(true)
    }
  }, [])

  const patchLastTurn = useCallback((fn: (t: AgentTurn) => AgentTurn) => {
    setAgentTurns((prev) => {
      if (prev.length === 0) return prev
      const next = prev.slice()
      next[next.length - 1] = fn(next[next.length - 1])
      return next
    })
  }, [])

  const handleAgentEvent = useCallback(
    (ev: AgentEvent) => {
      switch (ev.type) {
        case 'session_start':
          patchLastTurn((t) => ({ ...t, model: ev.model }))
          break
        case 'step_start':
          patchLastTurn((t) => ({ ...t, items: [...t.items, { kind: 'step', iteration: ev.iteration }] }))
          break
        case 'tool_call':
          patchLastTurn((t) => ({
            ...t,
            items: [...t.items, { kind: 'tool', step: { n: ev.n, name: ev.name, args: ev.args, pending: true } }],
          }))
          break
        case 'tool_result':
          patchLastTurn((t) => {
            // Match the most recent still-pending tool item (dispatch is serial).
            const items = t.items.slice()
            for (let i = items.length - 1; i >= 0; i--) {
              const it = items[i]
              if (it.kind === 'tool' && it.step.pending) {
                items[i] = {
                  kind: 'tool',
                  step: {
                    ...it.step,
                    pending: false,
                    ok: ev.ok,
                    status: ev.status,
                    result: ev.result,
                    error: ev.error,
                    cached: ev.cached,
                  },
                }
                break
              }
            }
            return { ...t, items }
          })
          break
        case 'awaiting_approval':
          patchLastTurn((t) => ({ ...t, note: `Awaiting approval for ${ev.name} — open it in Pending Actions.` }))
          break
        case 'final':
          patchLastTurn((t) => ({ ...t, final: ev.text }))
          break
        case 'limit_reached':
          patchLastTurn((t) => ({ ...t, note: `Stopped: reached ${ev.limit} (${ev.value}).` }))
          break
        case 'error':
          patchLastTurn((t) => ({ ...t, error: ev.error, running: false }))
          break
        case 'done':
          patchLastTurn((t) => ({
            ...t,
            running: false,
            meta: {
              iterations: ev.iterations,
              tool_calls: ev.tool_calls,
              tokens_in: ev.input_tokens,
              tokens_out: ev.output_tokens,
              duration_ms: ev.duration_ms,
            },
          }))
          setStreaming(false)
          break
      }
    },
    [patchLastTurn],
  )

  const handleAgentSubmit = (text: string) => {
    setAgentTurns((prev) => [...prev, { prompt: text, items: [], running: true }])
    setPrompt('')
    setStreaming(true)
    streamControllerRef.current?.abort()
    streamControllerRef.current = streamAgent(
      { prompt: text },
      {
        onEvent: handleAgentEvent,
        onError: (msg) => {
          patchLastTurn((t) => ({ ...t, error: msg, running: false }))
          setStreaming(false)
        },
      },
    )
  }

  const handleSubmit = () => {
    const text = prompt.trim()
    if (!text || streaming) return
    if (mode === 'agent') {
      handleAgentSubmit(text)
      return
    }
    // Capture history BEFORE addMessage — prevents the new message appearing
    // in both history and prompt (duplicate turn bug, closes #303)
    const history = messages
      .filter(m => !m.error)
      .slice(-10)
      .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }))
    addMessage({ role: 'user', content: text })
    // Pre-create the assistant placeholder so deltas append to a stable
    // bubble; the typing dots render on this bubble while streaming=true.
    addMessage({ role: 'assistant', content: '', streaming: true })
    setPrompt('')
    setStreaming(true)
    streamControllerRef.current?.abort()
    streamControllerRef.current = streamQuery(
      { prompt: text, intent: 'auto', history },
      {
        onDelta: (delta) => {
          appendToLastMessage(delta)
        },
        onDone: (final) => {
          patchLastMessage({
            streaming: false,
            error: final.error,
            meta: {
              model: final.model_used,
              tokens_in: final.input_tokens,
              tokens_out: final.output_tokens,
              duration_ms: final.duration_ms,
            },
          })
          setStreaming(false)
        },
        onError: (msg) => {
          patchLastMessage({ streaming: false, error: msg })
          setStreaming(false)
        },
      },
    )
  }

  const handleStop = () => {
    streamControllerRef.current?.abort()
    streamControllerRef.current = null
    if (mode === 'agent') {
      patchLastTurn((t) => ({ ...t, running: false, note: t.note ?? 'cancelled' }))
    } else {
      patchLastMessage({ streaming: false, error: 'cancelled' })
    }
    setStreaming(false)
  }

  const handlePromptChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value
    setPrompt(val)
    if (intentDebounceRef.current) clearTimeout(intentDebounceRef.current)
    intentDebounceRef.current = setTimeout(() => {
      setIntentHint(classifyIntentHint(val))
    }, 500)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  // Position style: use inline left/top when pos is known; else default anchor
  const posStyle = pos !== null
    ? { left: pos.x, top: pos.y, right: 'auto', bottom: 'auto' }
    : undefined

  const defaultAnchorClasses = pos === null ? 'bottom-6 right-6' : ''

  return (
    <>
      {/* Closed icon — only shown when panel is closed */}
      {!open && (
        <button
          ref={iconRef}
          onPointerDown={onPointerDownIcon}
          onPointerMove={e => onPointerMove(e as React.PointerEvent<HTMLElement>)}
          onPointerUp={e => onPointerUp(e as React.PointerEvent<HTMLElement>, true)}
          // Keyboard accessibility: Enter/Space fire a click with detail === 0
          // (pointer-initiated clicks have detail >= 1 and are handled in onPointerUp)
          onClick={e => { if (e.detail === 0) setOpen(true) }}
          style={posStyle}
          className={`fixed ${defaultAnchorClasses} z-50 w-14 h-14 bg-blue-600 hover:bg-blue-700 text-white rounded-full shadow-lg flex items-center justify-center transition-colors cursor-move select-none`}
          title="Open AI Assistant"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
        </button>
      )}

      {/* Panel — always mounted for fade, toggled via opacity/pointer-events */}
      <div
        ref={panelRef}
        style={posStyle}
        aria-hidden={!open}
        className={`fixed ${defaultAnchorClasses} z-50 w-96 max-h-[600px] flex flex-col bg-white/90 backdrop-blur-md border border-gray-200 rounded-xl shadow-2xl overflow-hidden transition-all duration-200 ${
          open
            ? 'opacity-100 scale-100 pointer-events-auto visible'
            : 'opacity-0 scale-95 pointer-events-none invisible'
        }`}
      >
        {/* Header — drag handle */}
        <div
          onPointerDown={onPointerDownHeader}
          onPointerMove={e => onPointerMove(e as React.PointerEvent<HTMLElement>)}
          onPointerUp={e => onPointerUp(e as React.PointerEvent<HTMLElement>, false)}
          className="flex items-center justify-between px-4 py-3 bg-blue-600 text-white cursor-move select-none"
        >
          <span className="font-semibold text-sm">AI Fleet Assistant</span>
          <div className="flex items-center gap-2">
            {/* Q&A ↔ Agent mode toggle */}
            <div className="flex rounded-md overflow-hidden border border-white/30 text-[11px] cursor-default select-auto">
              <button
                onClick={() => !streaming && setMode('qa')}
                disabled={streaming}
                className={`px-2 py-0.5 transition-colors ${mode === 'qa' ? 'bg-white text-blue-700' : 'text-white/80 hover:bg-white/10'} disabled:opacity-60`}
                title="Single-shot Q&A"
              >
                Q&amp;A
              </button>
              <button
                onClick={() => !streaming && setMode('agent')}
                disabled={streaming}
                className={`px-2 py-0.5 transition-colors ${mode === 'agent' ? 'bg-white text-blue-700' : 'text-white/80 hover:bg-white/10'} disabled:opacity-60`}
                title="Multi-tool agent run"
              >
                Agent
              </button>
            </div>
            {((mode === 'qa' && messages.length > 0) || (mode === 'agent' && agentTurns.length > 0)) && (
              <button
                onClick={() => (mode === 'agent' ? setAgentTurns([]) : clearMessages())}
                className="text-white/70 hover:text-white text-xs px-2 py-0.5 rounded border border-white/30 hover:border-white/60 transition-colors cursor-default select-auto"
                title="Clear history"
              >
                Clear
              </button>
            )}
            <button
              onClick={() => setOpen(false)}
              className="text-white/80 hover:text-white transition-colors cursor-default select-auto"
              title="Close"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
          {mode === 'agent' ? (
            <>
              {agentTurns.length === 0 && (
                <p className="text-sm text-gray-400 text-center mt-8">
                  Agent mode runs read-only tools to investigate — e.g. “why is mm7 degraded?”
                </p>
              )}
              {agentTurns.map((turn, ti) => (
                <div key={ti} className="space-y-2">
                  <div className="flex justify-end">
                    <div className="max-w-[85%] rounded-lg px-3 py-2 text-sm bg-blue-600 text-white">{turn.prompt}</div>
                  </div>
                  {turn.items.map((it, ii) =>
                    it.kind === 'step' ? (
                      <ToolStep key={ii} iteration={it.iteration} />
                    ) : (
                      <ToolResultCard key={ii} step={it.step} />
                    ),
                  )}
                  {turn.running && turn.items.length === 0 && (
                    <div className="flex space-x-1 py-1 px-1">
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                  )}
                  {turn.note && <p className="text-xs text-amber-600 px-1">{turn.note}</p>}
                  {turn.final && (
                    <div className="flex justify-start">
                      <div className="max-w-[85%] rounded-lg px-3 py-2 text-sm bg-gray-100 text-gray-900">
                        <pre className="whitespace-pre-wrap font-sans">{turn.final}</pre>
                      </div>
                    </div>
                  )}
                  {turn.error && (
                    <div className="flex justify-start">
                      <div className="max-w-[85%] rounded-lg px-3 py-2 text-sm bg-red-50 border border-red-200 text-red-700">
                        ⚠ {turn.error}
                      </div>
                    </div>
                  )}
                  {turn.meta && (
                    <div className="text-xs text-gray-400 px-1">
                      {turn.model} · {turn.meta.iterations} steps · {turn.meta.tool_calls} tools ·{' '}
                      {turn.meta.tokens_in}↑ {turn.meta.tokens_out}↓ · {turn.meta.duration_ms}ms
                    </div>
                  )}
                </div>
              ))}
              <div ref={bottomRef} />
            </>
          ) : (
          <>
          {messages.length === 0 && (
            <p className="text-sm text-gray-400 text-center mt-8">
              Ask anything about your fleet — node status, drift, playbooks, health metrics…
            </p>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                  msg.role === 'user'
                    ? 'bg-blue-600 text-white'
                    : msg.error
                    ? 'bg-red-50 border border-red-200 text-red-700'
                    : 'bg-gray-100 text-gray-900'
                }`}
              >
                {msg.error ? (
                  <span>⚠ {msg.error}</span>
                ) : msg.streaming && !msg.content ? (
                  // First-token latency: show the typing indicator inside the
                  // assistant bubble until the first delta arrives. Once any
                  // text exists the indicator hides and tokens render live.
                  <div className="flex space-x-1 py-1">
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                ) : (
                  <pre className="whitespace-pre-wrap font-sans">
                    {msg.content}
                    {msg.streaming && <span className="inline-block w-2 h-4 ml-0.5 bg-gray-500 animate-pulse align-text-bottom" aria-hidden="true" />}
                  </pre>
                )}
                {msg.meta && (
                  <div className="mt-1 text-xs text-gray-400">
                    {msg.meta.model} · {msg.meta.tokens_in}↑ {msg.meta.tokens_out}↓ · {msg.meta.duration_ms}ms
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
          </>
          )}
        </div>

        <div className="border-t border-gray-200 p-3 space-y-1.5">
          <div className="flex gap-2">
            <textarea
              value={prompt}
              onChange={handlePromptChange}
              onKeyDown={handleKeyDown}
              placeholder={mode === 'agent' ? 'Investigate with tools… (Enter to run)' : 'Ask about your fleet… (Enter to send)'}
              rows={2}
              className="flex-1 resize-none border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-400"
              disabled={streaming}
            />
            {streaming ? (
              <button
                onClick={handleStop}
                className="px-3 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-medium transition-colors self-end"
                title="Stop generation"
              >
                Stop
              </button>
            ) : (
              <button
                onClick={handleSubmit}
                disabled={!prompt.trim()}
                className="px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors self-end"
              >
                Send
              </button>
            )}
          </div>
          {prompt.trim() && mode === 'qa' && (
            <p className="text-xs text-gray-400">Detected: {intentHint}</p>
          )}
          {mode === 'agent' && (
            <p className="text-xs text-gray-400">Agent mode · read-only tools · bounded run</p>
          )}
        </div>
      </div>
    </>
  )
}
