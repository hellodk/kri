import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import { api } from '../api/client'

export function OidcCallbackPage() {
  const setTokens = useAuthStore((s) => s.setUser)
  const navigate = useNavigate()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const exchangeCode = params.get('exchange_code')

    if (!exchangeCode) {
      navigate('/login?error=oidc_failed', { replace: true })
      return
    }

    // Clear the exchange_code from the URL immediately before the async call
    // so it never lingers in browser history or server logs.
    window.history.replaceState({}, '', '/auth/callback')

    api
      .get<{ access_token: string; refresh_token: string }>(
        `/api/v1/auth/oidc/exchange?exchange_code=${encodeURIComponent(exchangeCode)}`,
      )
      .then((data) => {
        localStorage.setItem('access_token', data.access_token)
        localStorage.setItem('refresh_token', data.refresh_token)
        navigate('/', { replace: true })
      })
      .catch(() => {
        navigate('/login?error=oidc_failed', { replace: true })
      })
  }, [navigate, setTokens])

  return (
    <div
      className="min-h-screen flex items-center justify-center"
      style={{ background: 'linear-gradient(135deg, #0f0f23 0%, #1a1a3e 60%, #0f0f23 100%)' }}
    >
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-sm text-white/40">Completing sign-in…</p>
      </div>
    </div>
  )
}
