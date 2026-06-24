import { useEffect, useRef, useState } from 'react'
import { api, wsUrl, wsAuthProtocols } from '../api/client'
import { getAccessToken } from '../stores/authStore'

interface VNCViewerProps {
  nodeId: string
  nodeName: string
  onClose: () => void
}

/** Minimal shape of the @novnc/novnc RFB object (no bundled type declarations). */
interface RFBInstance {
  addEventListener(event: string, listener: (e: { detail?: { reason?: string } }) => void): void
  sendCredentials(creds: { password: string }): void
  disconnect(): void
  scaleViewport: boolean
  resizeSession: boolean
}

export function VNCViewer({ nodeId, nodeName, onClose }: VNCViewerProps) {
  const canvasRef = useRef<HTMLDivElement>(null)
  const rfbRef = useRef<RFBInstance | null>(null)
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('connecting')
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    let rfb: RFBInstance

    async function init() {
      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore — @novnc/novnc ships JS without bundled type declarations
      const { default: RFB } = await import('@novnc/novnc')

      const token = getAccessToken() || ''
      // JWT via subprotocol (#783); wss/ws from page protocol (#784). Query param
      // kept until the backend reads the subprotocol (see PR description).
      const url = wsUrl(`/api/v1/vnc/session/${nodeId}?token=${encodeURIComponent(token)}`)

      rfb = new RFB(canvasRef.current!, url, { wsProtocols: wsAuthProtocols(token) })
      rfbRef.current = rfb

      rfb.addEventListener('connect', () => setStatus('connected'))
      rfb.addEventListener('disconnect', (e: { detail?: { reason?: string } }) => {
        setStatus('disconnected')
        if (e.detail?.reason) setErrorMsg(e.detail.reason)
      })
      rfb.scaleViewport = true
      rfb.resizeSession = false

      rfb.addEventListener('credentialsrequired', async () => {
        try {
          const creds = await api.get<{password: string | null}>(`/api/v1/vnc/session/${nodeId}/creds`)
          if (creds.password) {
            rfb.sendCredentials({ password: creds.password })
          } else {
            setStatus('error')
            setErrorMsg('VNC requires a password — go to Node → Secrets → VNC Password')
            rfb.disconnect()
          }
        } catch {
          setStatus('error')
          setErrorMsg('Failed to retrieve VNC credentials')
          rfb.disconnect()
        }
      })
    }

    init().catch(e => {
      setStatus('error')
      setErrorMsg(e.message)
    })

    return () => {
      rfb?.disconnect()
    }
  }, [nodeId])

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-gray-950">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800 shrink-0">
        <div className="flex items-center gap-3">
          <span className={`w-2.5 h-2.5 rounded-full ${
            status === 'connected' ? 'bg-emerald-400 animate-pulse' :
            status === 'connecting' ? 'bg-amber-400 animate-pulse' :
            'bg-red-500'
          }`} />
          <span className="text-sm font-mono text-gray-300">
            VNC &rarr; <span className="text-purple-400">{nodeName}</span>
          </span>
          <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">{status}</span>
          <span className="text-xs text-amber-500 bg-gray-800 px-2 py-0.5 rounded">
            Session logged
          </span>
        </div>
        <button
          onClick={() => { rfbRef.current?.disconnect(); onClose() }}
          className="text-gray-400 hover:text-white text-lg px-3 py-1 hover:bg-gray-800 rounded"
        >
          &times; Close
        </button>
      </div>

      {/* Error / status */}
      {(status === 'error' || status === 'disconnected') && errorMsg && (
        <div className="flex items-center justify-center flex-1 text-red-400 text-sm gap-2">
          <span>&#9888;</span>
          <span>{errorMsg}</span>
        </div>
      )}

      {/* VNC canvas */}
      <div
        ref={canvasRef}
        className="flex-1 overflow-hidden bg-black"
        style={{ display: (status === 'error' || (status === 'disconnected' && errorMsg)) ? 'none' : 'block' }}
      />
    </div>
  )
}
