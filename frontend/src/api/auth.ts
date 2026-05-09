import { api } from './client'

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface UserResponse {
  id: string
  email: string
  display_name: string
  is_active: boolean
  is_superuser: boolean
  created_at: string
  updated_at: string
}

export const authApi = {
  register: (data: { email: string; password: string; display_name: string }) =>
    api.post<TokenResponse>('/auth/register', data),

  login: (data: { email: string; password: string }) =>
    api.post<TokenResponse>('/auth/login', data),

  refresh: (refreshToken: string) =>
    api.post<TokenResponse>('/auth/refresh', { refresh_token: refreshToken }),

  me: () => api.get<UserResponse>('/auth/me'),
}
