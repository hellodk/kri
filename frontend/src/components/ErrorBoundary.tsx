import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
  onReset?: () => void
}

interface State {
  hasError: boolean
  error: Error | null
}

/**
 * Catches render-time errors anywhere in its subtree and shows a recoverable
 * fallback instead of unmounting the whole app to a blank screen. Wrapping a
 * Suspense boundary also surfaces lazy chunk-load failures that would otherwise
 * fail silently.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface in the console for diagnostics; a real telemetry sink can hook here.
    console.error('Unhandled UI error:', error, info.componentStack)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
    this.props.onReset?.()
  }

  render() {
    if (!this.state.hasError) return this.props.children
    if (this.props.fallback !== undefined) return this.props.fallback

    return (
      <div
        role="alert"
        className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-4"
      >
        <span className="text-5xl" aria-hidden="true">⚠️</span>
        <h1 className="text-xl font-semibold text-gray-800">Something went wrong</h1>
        <p className="text-sm text-gray-500 max-w-sm">
          An unexpected error occurred while rendering this view. You can try again,
          and if the problem persists, reload the page.
        </p>
        <div className="flex gap-3 mt-2">
          <button
            onClick={this.handleReset}
            className="px-4 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm font-medium hover:bg-gray-50 transition-colors"
          >
            Try again
          </button>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-lg bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            Reload page
          </button>
        </div>
      </div>
    )
  }
}
