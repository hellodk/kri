import { api } from './client'
import type { TokenResponse, User } from '../types'

export interface OidcConfig {
  enabled: boolean
  issuer_url?: string
  client_id?: string
}

export const authApi = {
  login: (email: string, password: string) =>
    api.post<TokenResponse>('/auth/login', { email, password }),
  me: () => api.get<User>('/auth/me'),
  getOidcConfig: (): Promise<OidcConfig> =>
    fetch('/api/v1/auth/oidc/config').then((r) => r.json()),
}
