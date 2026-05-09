import { api } from './client'

export interface Network {
  id: string
  name: string
  subnet: string
  description: string | null
  created_at: string
}

export interface Device {
  id: string
  name: string
  user_id: string
  network_id: string
  public_key: string | null
  ip_address: string | null
  dns_enabled: boolean
  is_active: boolean
  tags: string[]
  last_handshake: string | null
  created_at: string
  updated_at: string
}

export interface PreAuthKey {
  id: string
  key: string
  network_id: string
  reusable: boolean
  expires_at: string
  created_at: string
  used_by: string[]
}

export interface ACLRule {
  id: string
  network_id: string
  src_tags: string[]
  dst_tags: string[]
  action: string
  priority: number
  created_at: string
}

export interface DNSEntry {
  id: string
  network_id: string
  domain: string
  address: string
  created_at: string
}

export const networksApi = {
  list: () => api.get<Network[]>('/networks'),
  get: (id: string) => api.get<Network>(`/networks/${id}`),
  create: (data: { name: string; subnet: string; description?: string }) =>
    api.post<Network>('/networks', data),
  update: (id: string, data: { name?: string; description?: string }) =>
    api.put<Network>(`/networks/${id}`, data),
  delete: (id: string) => api.delete<void>(`/networks/${id}`),

  listDevices: (networkId: string) =>
    api.get<Device[]>(`/networks/${networkId}/devices`),
  createDevice: (networkId: string, data: { name: string; dns_enabled?: boolean; tags?: string[] }) =>
    api.post<Device>(`/networks/${networkId}/devices`, data),

  listPreAuthKeys: (networkId: string) =>
    api.get<PreAuthKey[]>(`/networks/${networkId}/preauth-keys`),
  createPreAuthKey: (networkId: string, data: { reusable?: boolean; expires_in_hours?: number }) =>
    api.post<PreAuthKey>(`/networks/${networkId}/preauth-keys`, data),
  deletePreAuthKey: (networkId: string, keyId: string) =>
    api.delete<void>(`/networks/${networkId}/preauth-keys/${keyId}`),

  listACLs: (networkId: string) =>
    api.get<ACLRule[]>(`/networks/${networkId}/acls`),
  createACL: (networkId: string, data: { src_tags: string[]; dst_tags: string[]; action?: string; priority?: number }) =>
    api.post<ACLRule>(`/networks/${networkId}/acls`, data),
  updateACL: (networkId: string, ruleId: string, data: Partial<ACLRule>) =>
    api.put<ACLRule>(`/networks/${networkId}/acls/${ruleId}`, data),
  deleteACL: (networkId: string, ruleId: string) =>
    api.delete<void>(`/networks/${networkId}/acls/${ruleId}`),

  listDNS: (networkId: string) =>
    api.get<DNSEntry[]>(`/networks/${networkId}/dns`),
  createDNS: (networkId: string, data: { domain: string; address: string }) =>
    api.post<DNSEntry>(`/networks/${networkId}/dns`, data),
  deleteDNS: (networkId: string, entryId: string) =>
    api.delete<void>(`/networks/${networkId}/dns/${entryId}`),
}
