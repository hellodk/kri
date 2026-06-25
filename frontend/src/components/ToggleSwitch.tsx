interface ToggleSwitchProps {
  checked: boolean
  onChange: () => void
  disabled?: boolean
  loading?: boolean
  /** Accessible label describing what the switch controls. */
  ariaLabel?: string
  /** Native title tooltip shown on hover. */
  title?: string
}

/**
 * iOS-style toggle switch for independent on/off state.
 * Use for per-item booleans (e.g. enabled). For mutually-exclusive
 * single-select within a group, use a radio control instead.
 */
export function ToggleSwitch({
  checked,
  onChange,
  disabled = false,
  loading = false,
  ariaLabel,
  title,
}: ToggleSwitchProps) {
  const isDisabled = disabled || loading
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      aria-busy={loading || undefined}
      title={title}
      onClick={onChange}
      disabled={isDisabled}
      className={[
        'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-1',
        isDisabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
        checked ? 'bg-emerald-500 hover:bg-emerald-600' : 'bg-gray-200 hover:bg-gray-300',
      ].join(' ')}
    >
      <span
        className={[
          'inline-flex h-4 w-4 transform items-center justify-center rounded-full bg-white shadow transition-transform',
          checked ? 'translate-x-4' : 'translate-x-0.5',
        ].join(' ')}
      >
        {loading && (
          <span className="h-2 w-2 animate-spin rounded-full border border-gray-400 border-t-transparent" />
        )}
      </span>
    </button>
  )
}
