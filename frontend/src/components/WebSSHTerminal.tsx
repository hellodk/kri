import { useEffect, useRef, useState } from 'react'

interface WebSSHTerminalProps {
  nodeId: string
  nodeName: string
  onClose: () => void
  /** Optional: pre-existing session ID (informational only — displayed in header) */
  sessionId?: string | null
}

export function WebSSHTerminal({ nodeId, nodeName, onClose, sessionId }: WebSSHTerminalProps) {
  const termRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const terminalRef = useRef<any>(null)
  const [status, setStatus] = useState<'connecting' | 'connected' | 'closed' | 'error'>('connecting')
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    let cleanupFn: (() => void) | undefined

    async function init() {
      if (!termRef.current) return

      // Dynamically import xterm to avoid SSR issues
      const { Terminal } = await import('@xterm/xterm')
      const { FitAddon } = await import('xterm-addon-fit')
      await import('@xterm/xterm/css/xterm.css')

      const terminal = new Terminal({
        cursorBlink: true,
        fontSize: 13,
        fontFamily: '"JetBrains Mono", "Fira Code", monospace',
        theme: {
          background: '#0a0a1a',
          foreground: '#c8d3e0',
          cursor: '#7cb9e8',
          green: '#4ec9b0',
          cyan: '#7cb9e8',
          red: '#f48771',
        },
        scrollback: 5000,
      })
      const fitAddon = new FitAddon()
      terminal.loadAddon(fitAddon)
      terminal.open(termRef.current)
      requestAnimationFrame(() => { try { fitAddon.fit() } catch { /* ignore */ } })
      terminalRef.current = terminal

      // Get auth token from localStorage
      const token = localStorage.getItem('access_token') || ''
      const wsUrl = `ws://${window.location.host}/api/v1/ssh/session/${nodeId}?token=${encodeURIComponent(token)}`

      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => setStatus('connected')
      ws.onclose = () => {
        setStatus('closed')
        terminal.write('\r\n\x1b[33m[Session closed]\x1b[0m\r\n')
      }
      ws.onerror = () => {
        setStatus('error')
        setErrorMsg('WebSocket connection failed')
      }
      ws.onmessage = (e) => {
        terminal.write(e.data)
      }

      // Send keystrokes to server
      terminal.onData((data: string) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(data)
        }
      })

      // Handle resize
      const resizeObs = new ResizeObserver(() => {
        fitAddon.fit()
      })
      if (termRef.current) resizeObs.observe(termRef.current)

      cleanupFn = () => {
        resizeObs.disconnect()
        ws.close()
        terminal.dispose()
      }
    }

    init().catch((err) => {
      setStatus('error')
      setErrorMsg(String(err))
    })

    return () => {
      cleanupFn?.()
    }
  }, [nodeId])

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-gray-950">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-3">
          <span
            className={`w-2.5 h-2.5 rounded-full ${
              status === 'connected'
                ? 'bg-emerald-400 animate-pulse'
                : status === 'connecting'
                ? 'bg-amber-400 animate-pulse'
                : status === 'error'
                ? 'bg-red-500'
                : 'bg-gray-500'
            }`}
          />
          <span className="text-sm font-mono text-gray-300">
            SSH &rarr; <span className="text-cyan-400">{nodeName}</span>
          </span>
          <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
            {status}
          </span>
          <span className="text-xs text-amber-500 bg-gray-800 px-2 py-0.5 rounded">
            Session recorded
          </span>
          {sessionId && (
            <span className="text-xs text-gray-600 bg-gray-800 px-2 py-0.5 rounded font-mono" title="Session ID">
              {sessionId.slice(0, 8)}
            </span>
          )}
        </div>
        <button
          onClick={() => {
            wsRef.current?.close()
            onClose()
          }}
          className="text-gray-400 hover:text-white text-lg px-3 py-1 hover:bg-gray-800 rounded transition-colors"
        >
          x Close
        </button>
      </div>

      {/* Error state */}
      {status === 'error' && (
        <div className="flex-1 flex items-center justify-center text-red-400 text-sm">
          {errorMsg || 'Connection failed'}
        </div>
      )}

      {/* Terminal */}
      <div
        ref={termRef}
        className="flex-1 p-1"
        style={{ display: status === 'error' ? 'none' : 'block' }}
      />
    </div>
  )
}
