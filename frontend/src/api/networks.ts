import { api } from './client'

export interface Network {
  id: string
  name: string
  subnet: string
  description: string | null
  interface_name: string | null
  topology: string | null
  created_at: string
}

export interface Device {
  id: string
  name: string
  user_id: string | null
  network_id: string
  public_key: string | null
  ip_address: string | null
  dns_enabled: boolean
  is_active: boolean
  is_node_owned: boolean
  enrollment_status: string
  device_token_prefix: string | null
  enrolled_at: string | null
  last_seen_at: string | null
  last_handshake: string | null
  revoked_at: string | null
  exit_node_id: string | null
  tags: string[]
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

export interface EndpointCandidate {
  endpoint: string
  port: number
  source: string
  priority: number
  last_seen_at: string | null
  local_ip: string | null
  public_ip: string | null
  reachable: boolean
  latency_ms: number | null
  score: number
  preferred: boolean
}

export interface PeerInfo {
  public_key: string
  allowed_ips: string[]
  endpoint: string | null
  endpoint_port: number | null
  persistent_keepalive: number | null
  endpoint_candidates: EndpointCandidate[]
  relay_fallback: boolean
  relay_candidates: RelayCandidateInfo[] | null
  relay_required: boolean
}

export interface RelayCandidateInfo {
  relay_node: string
  relay_region: string
  relay_endpoint: string
  priority: number
  preferred: boolean
}

export interface DeviceConfigV2 {
  interface: {
    address: string
    dns: string[] | null
    mtu: number | null
  }
  peers: PeerInfo[]
  routes: string[]
  exit_node: string | null
  version: string
  revision: string
  generated_at: string
  hash: string
}

export interface RouteResponse {
  id: string
  device_id: string
  network_id: string
  prefix: string
  is_exit_node: boolean
  approved: boolean
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface AuditLogEntry {
  id: string
  action: string
  actor_id: string | null
  target_type: string | null
  target_id: string | null
  ip_address: string | null
  details: Record<string, unknown> | null
  created_at: string
}

export interface AuditLogPage {
  items: AuditLogEntry[]
  total: number
  skip: number
  limit: number
}

export interface HealthSummary {
  status: string
  wg_controller: { running: boolean; last_run: string | null }
  websocket: { active_connections: number }
  stun: { enabled: boolean; running: boolean; port: number | null }
  relay: { enabled: boolean; running: boolean; port: number | null }
}

export const networksApi = {
  list: () => api.get<Network[]>('/networks'),
  get: (id: string) => api.get<Network>(`/networks/${id}`),
  create: (data: { name: string; subnet: string; description?: string }) =>
    api.post<Network>('/networks', data),
  update: (id: string, data: { name?: string; description?: string; topology?: string }) =>
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

export const devicesApi = {
  list: () => api.get<Device[]>('/devices'),
  get: (id: string) => api.get<Device>(`/devices/${id}`),
  update: (id: string, data: Partial<Device>) =>
    api.put<Device>(`/devices/${id}`, data),
  delete: (id: string) => api.delete<void>(`/devices/${id}`),
  rotateKeys: (id: string) =>
    api.post<Device & { new_device_token?: string }>(`/devices/${id}/rotate-keys`),
  rotateToken: (id: string) =>
    api.post<{ device_token: string; device_token_prefix: string }>(`/devices/${id}/rotate-token`),
  getConfig: (id: string) =>
    api.get<{ config: string; filename: string }>(`/devices/${id}/config`),
  getConfigV2: (id: string) =>
    api.get<DeviceConfigV2>(`/devices/${id}/config-v2`),
  register: (data: { key: string; name: string }) =>
    api.post<Device>('/devices/register', data),
  revoke: (id: string) =>
    api.post<Device>(`/devices/${id}/revoke`),
  heartbeat: (id: string) =>
    api.post<{ status: string }>(`/devices/${id}/heartbeat`),
}

export const routesApi = {
  listByNetwork: (networkId: string) =>
    api.get<RouteResponse[]>(`/routes/networks/${networkId}`),
  listByDevice: (deviceId: string) =>
    api.get<RouteResponse[]>(`/routes/devices/${deviceId}`),
  advertise: (deviceId: string, data: { prefix: string; is_exit_node?: boolean }) =>
    api.post<RouteResponse>(`/routes/devices/${deviceId}/advertise`, data),
  approve: (routeId: string) =>
    api.post<RouteResponse>(`/routes/${routeId}/approve`),
  update: (routeId: string, data: { enabled?: boolean }) =>
    api.put<RouteResponse>(`/routes/${routeId}`, data),
  delete: (routeId: string) =>
    api.delete<void>(`/routes/${routeId}`),
  selectExitNode: (deviceId: string, data: { exit_node_id: string | null }) =>
    api.post<RouteResponse>(`/routes/devices/${deviceId}/exit-node`, data),
}

export const healthApi = {
  summary: () => api.get<HealthSummary>('/health'),
  live: () => api.get<Record<string, unknown>>('/health/live'),
  ready: () => api.get<Record<string, unknown>>('/health/ready'),
  startup: () => api.get<Record<string, unknown>>('/health/startup'),
}

export const auditApi = {
  list: (params?: { actor_id?: string; action?: string; target_type?: string; target_id?: string; skip?: number; limit?: number }) => {
    const searchParams = new URLSearchParams()
    if (params?.actor_id) searchParams.set('actor_id', params.actor_id)
    if (params?.action) searchParams.set('action', params.action)
    if (params?.target_type) searchParams.set('target_type', params.target_type)
    if (params?.target_id) searchParams.set('target_id', params.target_id)
    if (params?.skip) searchParams.set('skip', String(params.skip))
    if (params?.limit) searchParams.set('limit', String(params.limit))
    const qs = searchParams.toString()
    return api.get<AuditLogPage>(`/audit${qs ? `?${qs}` : ''}`)
  },
  actions: () => api.get<string[]>('/audit/actions'),
}

export const metricsApi = {
  get: () => fetch('/metrics').then(r => r.text()),
}

export const natApi = {
  punch: (data: { target_device_id: string; initiator_endpoint: string; initiator_port: number }) =>
    api.post<{ session_id: string; state: string; candidates: unknown[]; target_device_id: string }>('/nat/punch', data),
  getSession: (sessionId: string) =>
    api.get<Record<string, unknown>>(`/nat/${sessionId}`),
  reportResult: (sessionId: string, data: { success: boolean; error?: string }) =>
    api.post<Record<string, unknown>>(`/nat/${sessionId}/result`, data),
  validate: (sessionId: string) =>
    api.post<Record<string, unknown>>(`/nat/${sessionId}/validate`),
}

export const relayApi = {
  getCandidates: () =>
    api.get<RelayCandidateInfo[]>('/relay/candidates'),
  createSession: (data: { target_device_id: string }) =>
    api.post<Record<string, unknown>>('/relay/sessions', data),
  getSession: (sessionId: string) =>
    api.get<Record<string, unknown>>(`/relay/sessions/${sessionId}`),
}
