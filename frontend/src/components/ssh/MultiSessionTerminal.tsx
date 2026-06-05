/**
 * MultiSessionTerminal — renders one WebSSHTerminalPanel per tab.
 *
 * Only the active tab's panel is visible; inactive panels are hidden via CSS
 * (display:none) so xterm.js state is preserved and terminals stay connected.
 *
 * Each tab opens its own independent WebSocket to /api/v1/ssh/session/{nodeId}.
 */
import { useEffect, useRef } from 'react'
import type { SshTab } from './SshTabBar'

interface MultiSessionTerminalProps {
  tabs: SshTab[]
  activeTabId: string
  /** Called when a tab's WebSocket closes / errors so the parent can update UI */
  onTabStatusChange?: (tabId: string, status: 'connected' | 'closed' | 'error') => void
  /** Called when a credential decryption error is detected in the terminal output */
  onCredentialError?: (nodeId: string) => void
}

/**
 * SingleTerminalPanel — one xterm.js instance per SSH tab.
 * Connects on mount; cleans up on unmount.
 */
function SingleTerminalPanel({
  tab,
  isActive,
  onStatusChange,
  onCredentialError,
}: {
  tab: SshTab
  isActive: boolean
  onStatusChange?: (status: 'connected' | 'closed' | 'error') => void
  onCredentialError?: (nodeId: string) => void
}) {
  const termRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const terminalRef = useRef<unknown>(null)
  const cleanupRef = useRef<(() => void) | undefined>(undefined)

  useEffect(() => {
    let cancelled = false

    async function init() {
      if (!termRef.current) return

      const { Terminal } = await import('@xterm/xterm')
      const { FitAddon } = await import('xterm-addon-fit')
      await import('@xterm/xterm/css/xterm.css')

      if (cancelled) return

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
      terminal.open(termRef.current!)
      // Defer fit() to next animation frame — the container may have zero dimensions
      // immediately after open() if the terminal overlay was just mounted.
      requestAnimationFrame(() => { try { fitAddon.fit() } catch { /* ignore */ } })
      terminalRef.current = terminal

      const token = localStorage.getItem('access_token') || ''
      const wsUrl = `ws://${window.location.host}/api/v1/ssh/session/${tab.nodeId}?token=${encodeURIComponent(token)}`
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => onStatusChange?.('connected')
      ws.onclose = () => {
        onStatusChange?.('closed')
        terminal.write('\r\n\x1b[33m[Session closed]\x1b[0m\r\n')
      }
      ws.onerror = () => {
        onStatusChange?.('error')
        terminal.write('\r\n\x1b[31m[Connection failed]\x1b[0m\r\n')
      }
      ws.onmessage = (e) => {
        const data = e.data
        terminal.write(data)

        // Detect kri_event OSC sequence for credential errors
        // Format: \x1b]kri_event:{"type":"credential_error","code":"...","node_id":"..."}\x07
        if (typeof data === 'string' && data.includes('kri_event:')) {
          // eslint-disable-next-line no-control-regex -- intentional: \x07 is the BEL/OSC terminator in the kri_event OSC sequence
          const oscMatch = data.match(/kri_event:({[^}]+})\x07/)
          if (oscMatch) {
            try {
              const event = JSON.parse(oscMatch[1])
              if (event.type === 'credential_error' && event.node_id) {
                onCredentialError?.(event.node_id)
              }
            } catch {
              // Ignore JSON parse errors
            }
          }
        }
      }

      terminal.onData((data: string) => {
        if (ws.readyState === WebSocket.OPEN) ws.send(data)
      })

      const resizeObs = new ResizeObserver(() => {
        if (isActive) fitAddon.fit()
      })
      if (termRef.current) resizeObs.observe(termRef.current)

      cleanupRef.current = () => {
        resizeObs.disconnect()
        ws.close()
        terminal.dispose()
      }
    }

    init().catch((err) => {
      console.error('[MultiSessionTerminal] init error', err)
      onStatusChange?.('error')
    })

    return () => {
      cancelled = true
      cleanupRef.current?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab.nodeId, tab.id])

  // Refit when this panel becomes active
  useEffect(() => {
    if (isActive && termRef.current) {
      // Trigger ResizeObserver by re-observing; fitAddon is already observing
      // Give DOM a tick to layout before fitting
      const t = setTimeout(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          // Re-dispatch resize to force fitAddon to recalculate
          window.dispatchEvent(new Event('resize'))
        }
      }, 50)
      return () => clearTimeout(t)
    }
  }, [isActive])

  return (
    <div
      id={`ssh-panel-${tab.id}`}
      role="tabpanel"
      aria-labelledby={`ssh-tab-${tab.id}`}
      className="absolute inset-0"
      style={{ display: isActive ? 'block' : 'none' }}
    >
      <div ref={termRef} className="w-full h-full p-1" />
    </div>
  )
}

export function MultiSessionTerminal({
  tabs,
  activeTabId,
  onTabStatusChange,
  onCredentialError,
}: MultiSessionTerminalProps) {
  return (
    <div className="relative flex-1 overflow-hidden bg-gray-950">
      {tabs.map((tab) => (
        <SingleTerminalPanel
          key={tab.id}
          tab={tab}
          isActive={tab.id === activeTabId}
          onStatusChange={(status) => onTabStatusChange?.(tab.id, status)}
          onCredentialError={onCredentialError}
        />
      ))}
    </div>
  )
}
