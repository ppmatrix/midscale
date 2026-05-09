import { api } from './client'
import type { Device } from './networks'

export const devicesApi = {
  list: () => api.get<Device[]>('/devices'),
  get: (id: string) => api.get<Device>(`/devices/${id}`),
  update: (id: string, data: Partial<Device>) =>
    api.put<Device>(`/devices/${id}`, data),
  delete: (id: string) => api.delete<void>(`/devices/${id}`),
  rotateKeys: (id: string) =>
    api.post<Device>(`/devices/${id}/rotate-keys`),
  getConfig: (id: string) =>
    api.get<{ config: string; filename: string }>(`/devices/${id}/config`),
  register: (data: { key: string; name: string }) =>
    api.post<Device>('/devices/register', data),
}
