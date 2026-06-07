import { useState, useRef, useEffect, useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'
import { llmApi } from '../api/llm'
import type { LLMQueryResponse } from '../api/llm'
import { useLLMStore } from '../stores/llmStore'

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
  const { messages, addMessage, clearMessages } = useLLMStore()
  const bottomRef = useRef<HTMLDivElement>(null)
  const intentDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
  }, [messages])

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

  const mutation = useMutation({
    mutationFn: ({ text, history }: { text: string; history: Array<{ role: 'user' | 'assistant'; content: string }> }) =>
      llmApi.submitQuery({ prompt: text, intent: 'auto', history }),
    onSuccess: (data: LLMQueryResponse) => {
      addMessage({
        role: 'assistant',
        content: data.result,
        meta: {
          model: data.model_used,
          tokens_in: data.input_tokens,
          tokens_out: data.output_tokens,
          duration_ms: data.duration_ms,
        },
      })
    },
    onError: (err: Error) => {
      addMessage({
        role: 'assistant',
        content: '',
        error: err.message || 'LLM call failed.',
      })
    },
  })

  const handleSubmit = () => {
    const text = prompt.trim()
    if (!text || mutation.isPending) return
    // Capture history BEFORE addMessage — prevents the new message appearing
    // in both history and prompt (duplicate turn bug, closes #303)
    const history = messages
      .filter(m => !m.error)
      .slice(-10)
      .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }))
    addMessage({ role: 'user', content: text })
    setPrompt('')
    mutation.mutate({ text, history })
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
            {messages.length > 0 && (
              <button
                onClick={clearMessages}
                className="text-white/70 hover:text-white text-xs px-2 py-0.5 rounded border border-white/30 hover:border-white/60 transition-colors cursor-default select-auto"
                title="Clear chat history"
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
                ) : (
                  <pre className="whitespace-pre-wrap font-sans">{msg.content}</pre>
                )}
                {msg.meta && (
                  <div className="mt-1 text-xs text-gray-400">
                    {msg.meta.model} · {msg.meta.tokens_in}↑ {msg.meta.tokens_out}↓ · {msg.meta.duration_ms}ms
                  </div>
                )}
              </div>
            </div>
          ))}
          {mutation.isPending && (
            <div className="flex justify-start">
              <div className="bg-gray-100 rounded-lg px-3 py-2">
                <div className="flex space-x-1">
                  <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-gray-200 p-3 space-y-1.5">
          <div className="flex gap-2">
            <textarea
              value={prompt}
              onChange={handlePromptChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your fleet… (Enter to send)"
              rows={2}
              className="flex-1 resize-none border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-400"
              disabled={mutation.isPending}
            />
            <button
              onClick={handleSubmit}
              disabled={!prompt.trim() || mutation.isPending}
              className="px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors self-end"
            >
              Send
            </button>
          </div>
          {prompt.trim() && (
            <p className="text-xs text-gray-400">Detected: {intentHint}</p>
          )}
        </div>
      </div>
    </>
  )
}
