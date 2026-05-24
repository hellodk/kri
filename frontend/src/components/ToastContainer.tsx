import { useToastStore } from '../stores/toastStore'

export function ToastContainer() {
  const { toasts, remove } = useToastStore()
  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`flex items-center gap-3 px-4 py-3 rounded-lg shadow-xl text-sm text-white min-w-64 max-w-sm pointer-events-auto border ${
            t.type === 'success'
              ? 'bg-emerald-900/90 border-emerald-700/60 shadow-emerald-900/40'
              : t.type === 'error'
              ? 'bg-red-900/90 border-red-700/60 shadow-red-900/40'
              : 'bg-gray-800/90 border-gray-700/60'
          }`}
          style={{ backdropFilter: 'blur(8px)' }}
        >
          <span className="flex-1">{t.message}</span>
          <button
            onClick={() => remove(t.id)}
            className="text-white/50 hover:text-white transition-colors ml-1 text-lg leading-none"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
