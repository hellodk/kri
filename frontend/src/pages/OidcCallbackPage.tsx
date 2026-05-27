import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'

export function OidcCallbackPage() {
  const setTokens = useAuthStore((s) => s.setUser)
  const navigate = useNavigate()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const accessToken = params.get('access_token')
    const refreshToken = params.get('refresh_token')

    if (accessToken && refreshToken) {
      localStorage.setItem('access_token', accessToken)
      localStorage.setItem('refresh_token', refreshToken)
      // Clear tokens from URL before navigating
      window.history.replaceState({}, '', '/auth/callback')
      navigate('/', { replace: true })
    } else {
      navigate('/login?error=oidc_failed', { replace: true })
    }
  }, [navigate, setTokens])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="w-8 h-8 border-2 border-brand-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-sm text-gray-500">Completing sign-in…</p>
      </div>
    </div>
  )
}
