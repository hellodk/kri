import { useEffect, useState } from 'react'
import { useToastStore, type Toast } from '../stores/toastStore'

function ToastItem({ toast, onRemove }: { toast: Toast; onRemove: (id: string) => void }) {
  const [show, setShow] = useState(false)
  useEffect(() => {
    const t = requestAnimationFrame(() => setShow(true))
    return () => cancelAnimationFrame(t)
  }, [])
  return (
    <div
      className={`flex items-center gap-3 px-4 py-3 rounded-lg shadow-xl text-sm text-white min-w-64 max-w-sm pointer-events-auto border transition-all duration-500 ease-out ${
        show ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'
      } ${
        toast.type === 'success'
          ? 'bg-emerald-900/90 border-emerald-700/60 shadow-emerald-900/40'
          : toast.type === 'error'
          ? 'bg-red-900/90 border-red-700/60 shadow-red-900/40'
          : 'bg-gray-800/90 border-gray-700/60'
      }`}
      style={{ backdropFilter: 'blur(8px)' }}
    >
      <span className="flex-1">{toast.message}</span>
      <button
        onClick={() => onRemove(toast.id)}
        className="text-white/50 hover:text-white transition-colors ml-1 text-lg leading-none"
      >
        ×
      </button>
    </div>
  )
}

export function ToastContainer() {
  const { toasts, remove } = useToastStore()
  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onRemove={remove} />
      ))}
    </div>
  )
}
