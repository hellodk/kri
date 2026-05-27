import { useState, useRef, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { llmApi } from '../api/llm'
import type { LLMQueryResponse } from '../api/llm'
import { useLLMStore } from '../stores/llmStore'

export default function LLMAssistant() {
  const [open, setOpen] = useState(false)
  const [prompt, setPrompt] = useState('')
  const { messages, addMessage, clearMessages } = useLLMStore()
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const mutation = useMutation({
    mutationFn: (text: string) =>
      llmApi.submitQuery({ prompt: text, intent: 'explain' }),
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
    addMessage({ role: 'user', content: text })
    setPrompt('')
    mutation.mutate(text)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <>
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-50 w-14 h-14 bg-blue-600 hover:bg-blue-700 text-white rounded-full shadow-lg flex items-center justify-center transition-colors"
          title="Open AI Assistant"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
        </button>
      )}

      {open && (
        <div className="fixed bottom-6 right-6 z-50 w-96 max-h-[600px] flex flex-col bg-white border border-gray-200 rounded-xl shadow-2xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 bg-blue-600 text-white">
            <span className="font-semibold text-sm">AI Fleet Assistant</span>
            <div className="flex items-center gap-2">
              {messages.length > 0 && (
                <button
                  onClick={clearMessages}
                  className="text-white/70 hover:text-white text-xs px-2 py-0.5 rounded border border-white/30 hover:border-white/60 transition-colors"
                  title="Clear chat history"
                >
                  Clear
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                className="text-white/80 hover:text-white transition-colors"
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

          <div className="border-t border-gray-200 p-3 flex gap-2">
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
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
        </div>
      )}
    </>
  )
}
