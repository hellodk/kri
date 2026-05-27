import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  meta?: { model: string; tokens_in: number; tokens_out: number; duration_ms: number }
  error?: string
}

interface LLMStore {
  messages: ChatMessage[]
  addMessage: (msg: Omit<ChatMessage, 'timestamp'>) => void
  clearMessages: () => void
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
    }),
    { name: 'llm-chat-history' }
  )
)
