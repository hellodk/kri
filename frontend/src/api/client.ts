import { useAuthStore } from '../stores/authStore'

export class ApiError extends Error {
  status: number
  errorCode: string | null
  constructor(status: number, message: string, errorCode: string | null = null) {
    super(message)
    this.status = status
    this.errorCode = errorCode
    this.name = 'ApiError'
  }
}

async function tryRefresh(): Promise<boolean> {
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) return false
  try {
    const res = await fetch('/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) return false
    const data = await res.json()
    localStorage.setItem('access_token', data.access_token)
    if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token)
    return true
  } catch {
    return false
  }
}

async function request<T>(path: string, init?: RequestInit, retry = true): Promise<T> {
  const token = localStorage.getItem('access_token')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string>),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
  const res = await fetch(path, { ...init, headers })

  if (res.status === 401 && retry) {
    // Don't attempt refresh or redirect when the login endpoint itself rejects —
    // let the caller (LoginPage) handle the error and display it to the user.
    if (path.includes('/auth/login')) {
      const body = await res.json().catch(() => ({}))
      throw new ApiError(401, body.detail ?? 'Invalid credentials', body.error_code ?? null)
    }
    const refreshed = await tryRefresh()
    if (refreshed) return request<T>(path, init, false)
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    useAuthStore.setState({ user: null, hydrating: false })
    window.location.href = '/login'
    throw new ApiError(401, 'Session expired')
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.detail ?? res.statusText, body.error_code ?? null)
  }

  if (res.status === 204) return undefined as unknown as T
  return res.json()
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  postForm: async <T>(path: string, form: FormData, retry = true): Promise<T> => {
    // Do NOT set Content-Type — browser must set it with the multipart boundary.
    const token = localStorage.getItem('access_token')
    const res = await fetch(path, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    })
    if (res.status === 401 && retry) {
      const refreshed = await tryRefresh()
      if (refreshed) return api.postForm<T>(path, form, false)
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      useAuthStore.setState({ user: null, hydrating: false })
      window.location.href = '/login'
      throw new ApiError(401, 'Session expired')
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new ApiError(res.status, body.detail ?? res.statusText, body.error_code ?? null)
    }
    return res.json()
  },
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: (path: string) => request<void>(path, { method: 'DELETE' }),
}
