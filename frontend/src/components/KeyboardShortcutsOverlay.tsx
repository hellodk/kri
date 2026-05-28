import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts'

interface Props {
  open: boolean
  onClose: () => void
}

export function KeyboardShortcutsOverlay({ open, onClose }: Props) {
  useKeyboardShortcuts({ Escape: onClose }, open)

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        className="bg-[#111827] border border-gray-700 rounded-xl p-6 w-80 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-white font-semibold text-lg mb-4">Keyboard Shortcuts</h2>
        <table className="w-full text-sm">
          <tbody className="space-y-2">
            {[
              ['?', 'Show this overlay'],
              ['Escape', 'Close modal / overlay'],
              ['Ctrl+K or /', 'Focus search / filter'],
            ].map(([key, desc]) => (
              <tr key={key} className="border-b border-gray-800">
                <td className="py-2 pr-4">
                  <kbd className="bg-gray-800 text-gray-200 px-2 py-0.5 rounded text-xs font-mono">
                    {key}
                  </kbd>
                </td>
                <td className="py-2 text-gray-400">{desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          onClick={onClose}
          className="mt-4 text-xs text-gray-500 hover:text-gray-300"
        >
          Press Escape or ? to close
        </button>
      </div>
    </div>
  )
}
