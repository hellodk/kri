import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  meta?: { model: string; tokens_in: number; tokens_out: number; duration_ms: number }
  error?: string
  // True while a streaming response is mid-flight; flips to false on the
  // `done` event. Used by the UI to render the typing indicator on the
  // bubble itself rather than as a separate row.
  streaming?: boolean
}

interface LLMStore {
  messages: ChatMessage[]
  addMessage: (msg: Omit<ChatMessage, 'timestamp'>) => void
  clearMessages: () => void
  // Append a token-delta to the last message in place (no re-render of
  // the entire array). The last message must already be an assistant
  // entry — typically created with streaming: true just before the
  // first delta arrives.
  appendToLastMessage: (delta: string) => void
  // Patch the last message (e.g. set meta + clear streaming flag on
  // the SSE `done` event, or set error on `error`).
  patchLastMessage: (patch: Partial<ChatMessage>) => void
}

export const useLLMStore = create<LLMStore>()(
  persist(
    (set) => ({
      messages: [],
      addMessage: (msg) =>
        set((s) => ({
          messages: [...s.messages, { ...msg, timestamp: Date.now() }],
        })),
      clearMessages: () => set({ messages: [] }),
      appendToLastMessage: (delta) =>
        set((s) => {
          if (!s.messages.length) return s
          const next = s.messages.slice()
          const last = { ...next[next.length - 1] }
          last.content = (last.content || '') + delta
          next[next.length - 1] = last
          return { messages: next }
        }),
      patchLastMessage: (patch) =>
        set((s) => {
          if (!s.messages.length) return s
          const next = s.messages.slice()
          next[next.length - 1] = { ...next[next.length - 1], ...patch }
          return { messages: next }
        }),
    }),
    { name: 'llm-chat-history' }
  )
)
