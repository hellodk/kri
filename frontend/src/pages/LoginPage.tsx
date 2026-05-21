import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../api/auth'
import { useAuthStore } from '../stores/authStore'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const setUser = useAuthStore((s) => s.setUser)

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
      setError(err instanceof Error ? err.message : 'Login failed')
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
            Fleet visibility<br />for Mac infrastructure
          </h2>
          <p className="text-white/40 text-lg leading-relaxed">
            Drift detection, SBOM analysis, and execution history for your entire Mac fleet.
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

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-white/55 text-sm font-medium mb-1.5">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@fleet.local"
                className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-white/20 focus:outline-none focus:border-brand-500 focus:bg-white/8 transition-colors"
              />
            </div>
            <div>
              <label className="block text-white/55 text-sm font-medium mb-1.5">Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-white/20 focus:outline-none focus:border-brand-500 focus:bg-white/8 transition-colors"
              />
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
          </form>
        </div>
      </div>
    </div>
  )
}
