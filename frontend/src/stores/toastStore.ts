import { create } from 'zustand'

export interface Toast {
  id: string
  message: string
  type: 'success' | 'error' | 'info' | 'warning'
}

const DISMISS_MS: Record<Toast['type'], number | null> = {
  success: 3000,
  info: 4000,
  warning: 6000,
  error: null, // no auto-dismiss — user must manually close
}

interface ToastState {
  toasts: Toast[]
  add: (message: string, type?: Toast['type']) => void
  remove: (id: string) => void
}

export const useToastStore = create<ToastState>()((set) => ({
  toasts: [],
  add: (message, type = 'success') => {
    const id = Math.random().toString(36).slice(2)
    set((s) => ({ toasts: [...s.toasts, { id, message, type }] }))
    const delay = DISMISS_MS[type]
    if (delay !== null) {
      setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), delay)
    }
  },
  remove: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))
