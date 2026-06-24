import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuthStore } from '../stores/authStore'
import { loginErrorMessage } from './loginError'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [oidcEnabled, setOidcEnabled] = useState(false)
  const navigate = useNavigate()
  const setUser = useAuthStore((s) => s.setUser)
  const [searchParams] = useSearchParams()
  const [ssoError, setSsoError] = useState(!!searchParams.get('error'))

  useEffect(() => {
    authApi.getOidcConfig().then((cfg) => setOidcEnabled(cfg.enabled)).catch(() => {})
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const tokens = await authApi.login(email, password)
      localStorage.setItem('access_token', tokens.access_token)
      localStorage.setItem('refresh_token', tokens.refresh_token)
      const user = await authApi.me()
      setUser(user)
      navigate('/fleet')
    } catch (err: unknown) {
      setError(loginErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex" style={{ background: 'linear-gradient(135deg, #0f0f23 0%, #1a1a3e 60%, #0f0f23 100%)' }}>
      {/* Left — branding */}
      <div className="hidden lg:flex flex-col justify-between w-1/2 p-12 border-r border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-600 flex items-center justify-center shadow-lg shadow-brand-600/40">
            <span className="text-white font-black text-lg tracking-tighter">k</span>
          </div>
          <span className="text-white font-bold text-2xl tracking-tight">kri</span>
        </div>
        <div>
          <h2 className="text-white text-4xl font-bold leading-tight mb-4">
            Fleet visibility<br />for your build infrastructure
          </h2>
          <p className="text-white/40 text-lg leading-relaxed">
            Drift detection, SBOM scanning, and remote ops for your entire build fleet.
          </p>
        </div>
        <div className="flex gap-6 text-white/20 text-sm font-mono">
          <span>Drift Detection</span>
          <span>·</span>
          <span>SBOM Pipeline</span>
          <span>·</span>
          <span>Salt Integration</span>
        </div>
      </div>

      {/* Right — form */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-sm">
          {/* Mobile logo */}
          <div className="flex items-center gap-3 mb-8 lg:hidden">
            <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
              <span className="text-white font-black">k</span>
            </div>
            <span className="text-white font-bold text-xl">kri</span>
          </div>

          <h1 className="text-white text-2xl font-bold mb-1">Sign in</h1>
          <p className="text-white/35 text-sm mb-8">Enter your credentials to access the fleet dashboard</p>

          {ssoError && (
            <div className="mb-4 flex items-start gap-3 p-4 bg-red-50 border border-red-200 rounded-lg">
              <span className="text-red-600 text-sm font-medium flex-1">
                Single sign-on failed. Please try again or sign in with email and password.
              </span>
              <button onClick={() => setSsoError(false)} className="text-red-400 hover:text-red-600 text-lg leading-none">✕</button>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-white/55 text-sm font-medium mb-1.5">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@fleet.local"
                className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-white/20 focus:outline-hidden focus:border-brand-500 focus:bg-white/8 transition-colors"
              />
            </div>
            <div>
              <label className="block text-white/55 text-sm font-medium mb-1.5">Password</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-4 py-3 pr-11 rounded-lg bg-white/5 border border-white/10 text-white placeholder-white/20 focus:outline-hidden focus:border-brand-500 focus:bg-white/8 transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 transition-colors p-1"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? (
                    <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21" />
                    </svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
            {error && (
              <div role="alert" className="px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                {error}
              </div>
            )}
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-brand-600 hover:bg-brand-500 text-white rounded-lg font-semibold transition-colors disabled:opacity-50 shadow-lg shadow-brand-600/25 mt-2"
            >
              {loading ? 'Signing in…' : 'Sign in'}
            </button>

            {oidcEnabled && (
              <div className="relative flex items-center my-4">
                <div className="flex-1 border-t border-white/10" />
                <span className="px-3 text-xs text-white/30">or</span>
                <div className="flex-1 border-t border-white/10" />
              </div>
            )}
            {oidcEnabled && (
              <a
                href="/api/v1/auth/oidc/login"
                className="flex items-center justify-center gap-2 w-full py-2.5 border border-white/15 text-white/70 rounded-lg text-sm font-medium hover:bg-white/5 hover:text-white transition-colors"
              >
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg" style={{flexShrink:0}}>
                  <circle cx="9" cy="9" r="7.5" stroke="currentColor" strokeWidth="1.5" fill="none" />
                  <path d="M9 4.5v9M4.5 9h9" stroke="currentColor" strokeWidth="1.5" />
                </svg>
                Sign in with SSO
              </a>
            )}
          </form>
        </div>
      </div>
    </div>
  )
}
