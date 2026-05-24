import { api } from './client'
import type { TokenResponse, User } from '../types'

export const authApi = {
  login: (email: string, password: string) =>
    api.post<TokenResponse>('/auth/login', { email, password }),
  me: () => api.get<User>('/auth/me'),
}
