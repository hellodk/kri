import { Navigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('access_token')
  const user = useAuthStore((s) => s.user)
  if (!token || !user) return <Navigate to="/login" replace />
  return <>{children}</>
}
