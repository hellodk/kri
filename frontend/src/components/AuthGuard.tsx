import { useEffect, useRef } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import { authApi } from '../api/auth'

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('access_token')
  const user = useAuthStore((s) => s.user)
  const hydrating = useAuthStore((s) => s.hydrating)
  const setUser = useAuthStore((s) => s.setUser)
  const setHydrating = useAuthStore((s) => s.setHydrating)
  // Use a ref to prevent multiple concurrent /auth/me calls
  const fetchingRef = useRef(false)

  useEffect(() => {
    if (token && !user && !fetchingRef.current) {
      fetchingRef.current = true
      setHydrating(true)
      authApi
        .me()
        .then((me) => {
          setUser(me)
          fetchingRef.current = false
        })
        .catch(() => {
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
          setHydrating(false)
          fetchingRef.current = false
        })
    }
  }, [token, user, setUser, setHydrating])

  if (!token) return <Navigate to="/login" replace />
  if (hydrating || (token && !user)) return null  // waiting for /auth/me
  return <>{children}</>
}
