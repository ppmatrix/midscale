import { useEffect, useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { networksApi, devicesApi, routesApi, auditApi, type Network, type Device, type PreAuthKey, type ACLRule, type DNSEntry, type RouteResponse, type AuditLogEntry } from '../api/networks'
import StatusBadge from '../components/StatusBadge'
import EmptyState from '../components/EmptyState'
import LoadingSpinner from '../components/LoadingSpinner'
import SectionCard from '../components/SectionCard'
import CopyButton from '../components/CopyButton'
import TopologyGraph from '../components/TopologyGraph'

type Tab = 'devices' | 'topology' | 'acls' | 'dns' | 'keys' | 'routes' | 'activity'

export default function NetworkDetail() {
  const { networkId } = useParams<{ networkId: string }>()
  const navigate = useNavigate()
  const [network, setNetwork] = useState<Network | null>(null)
  const [devices, setDevices] = useState<Device[]>([])
  const [acls, setAcls] = useState<ACLRule[]>([])
  const [dns, setDns] = useState<DNSEntry[]>([])
  const [keys, setKeys] = useState<PreAuthKey[]>([])
  const [routes, setRoutes] = useState<RouteResponse[]>([])
  const [audit, setAudit] = useState<AuditLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<Tab>('devices')
  const [deviceName, setDeviceName] = useState('')

  const [keyReusable, setKeyReusable] = useState(false)
  const [keyExpiry, setKeyExpiry] = useState('24')
  const [serverUrl, setServerUrl] = useState(window.location.origin)
  const [newTopology, setNewTopology] = useState('')

  const fetchData = () => {
    if (!networkId) return
    setError('')
    const promises: Promise<unknown>[] = [
      networksApi.get(networkId).then(setNetwork),
      networksApi.listDevices(networkId).then(setDevices),
      networksApi.listACLs(networkId).then(setAcls),
      networksApi.listDNS(networkId).then(setDns),
      networksApi.listPreAuthKeys(networkId).then(setKeys),
      routesApi.listByNetwork(networkId).then(setRoutes).catch(() => setRoutes([])),
      auditApi.list({ target_type: 'network', target_id: networkId, limit: 20 }).then(p => setAudit(p.items)).catch(() => setAudit([])),
    ]
    Promise.all(promises).catch((err) => {
      setError(err instanceof Error ? err.message : 'Failed to load network')
      if (!network) navigate('/')
    }).finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchData()
  }, [networkId])

  const addDevice = async () => {
    if (!networkId || !deviceName) return
    try {
      const dev = await networksApi.createDevice(networkId, { name: deviceName })
      setDevices([...devices, dev])
      setDeviceName('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create device')
    }
  }

  const createKey = async () => {
    if (!networkId) return
    try {
      const data: { reusable?: boolean; expires_in_hours?: number } = {}
      if (keyReusable) data.reusable = true
      const hours = parseInt(keyExpiry)
      if (hours > 0) data.expires_in_hours = hours
      const key = await networksApi.createPreAuthKey(networkId, data)
      setKeys([...keys, key])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create key')
    }
  }

  const deleteKey = async (keyId: string) => {
    if (!networkId) return
    try {
      await networksApi.deletePreAuthKey(networkId, keyId)
      setKeys(keys.filter(k => k.id !== keyId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete key')
    }
  }

  const handleTopologyChange = async (topology: string) => {
    if (!networkId) return
    try {
      const updated = await networksApi.update(networkId, { topology })
      setNetwork(updated)
      setNewTopology('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update topology')
    }
  }

  const handleApproveRoute = async (routeId: string) => {
    try {
      await routesApi.approve(routeId)
      setRoutes(routes.map(r => r.id === routeId ? { ...r, approved: true } : r))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve route')
    }
  }

  const handleToggleRoute = async (routeId: string, enabled: boolean) => {
    try {
      await routesApi.update(routeId, { enabled })
      setRoutes(routes.map(r => r.id === routeId ? { ...r, enabled } : r))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update route')
    }
  }

  const handleRevoke = async (deviceId: string) => {
    try {
      await devicesApi.revoke(deviceId)
      setDevices(devices.map(d => d.id === deviceId ? { ...d, is_active: false, enrollment_status: 'revoked' } : d))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revoke device')
    }
  }

  if (loading || !network) return <LoadingSpinner />

  const onlineDevices = devices.filter(d => d.is_active)
  const exitNodes = devices.filter(d => d.exit_node_id)

  const topologyLinks = useMemo(() => {
    const links: { source_id: string; target_id: string; type: 'direct' | 'relay' | 'hub' | 'offline' }[] = []
    const serverDev = devices.find(d => d.name === '__midscale_server__')
    const serverId = serverDev?.id || '__hub__'
    const activeDevs = devices.filter(d => d.name !== '__midscale_server__')

    const topo = network.topology || 'star'

    activeDevs.forEach(d => {
      if (topo === 'star') {
        links.push({ source_id: d.id, target_id: serverId, type: d.is_active ? 'hub' : 'offline' })
      } else if (topo === 'mesh') {
        links.push({ source_id: d.id, target_id: serverId, type: d.is_active ? 'direct' : 'hub' })
        activeDevs.forEach(other => {
          if (d.id < other.id) {
            links.push({ source_id: d.id, target_id: other.id, type: d.is_active && other.is_active ? 'direct' : 'offline' })
          }
        })
      } else {
        links.push({ source_id: d.id, target_id: serverId, type: d.is_active ? 'hub' : 'offline' })
      }
    })
    return links
  }, [devices, network.topology])

  const tabs: { key: Tab; label: string }[] = [
    { key: 'devices', label: `Devices (${devices.length})` },
    { key: 'topology', label: 'Topology' },
    { key: 'acls', label: `ACLs (${acls.length})` },
    { key: 'dns', label: `DNS (${dns.length})` },
    { key: 'keys', label: `Pre-auth Keys (${keys.length})` },
    { key: 'routes', label: `Routes (${routes.length})` },
    { key: 'activity', label: 'Activity' },
  ]

  return (
    <div className="space-y-6">
      {error && <div className="bg-red-50 text-red-700 p-3 rounded text-sm border border-red-200">{error}</div>}

      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">{network.name}</h1>
            {network.topology && <StatusBadge status={network.topology} />}
          </div>
          <p className="text-gray-500 text-sm mt-1">
            {network.subnet} &middot; {devices.length} devices, {onlineDevices.length} online
            {network.description && <span> &middot; {network.description}</span>}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-white rounded-lg shadow px-4 py-3 border-l-4 border-indigo-500">
          <p className="text-xs text-gray-500">Devices</p>
          <p className="text-xl font-bold">{devices.length}</p>
        </div>
        <div className="bg-white rounded-lg shadow px-4 py-3 border-l-4 border-green-500">
          <p className="text-xs text-gray-500">Online</p>
          <p className="text-xl font-bold">{onlineDevices.length}</p>
        </div>
        <div className="bg-white rounded-lg shadow px-4 py-3 border-l-4 border-blue-500">
          <p className="text-xs text-gray-500">Routes</p>
          <p className="text-xl font-bold">{routes.length}</p>
        </div>
        <div className="bg-white rounded-lg shadow px-4 py-3 border-l-4 border-yellow-500">
          <p className="text-xs text-gray-500">Exit Nodes</p>
          <p className="text-xl font-bold">{exitNodes.length}</p>
        </div>
      </div>

      <div className="border-b border-gray-200 overflow-x-auto">
        <div className="flex gap-4 min-w-max">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`pb-2 px-1 text-sm font-medium border-b-2 transition ${tab === t.key ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'devices' && (
        <div className="space-y-4">
          <div className="flex gap-2">
            <input
              type="text"
              value={deviceName}
              onChange={(e) => setDeviceName(e.target.value)}
              placeholder="New device name"
              className="rounded border border-gray-300 px-3 py-2 text-sm w-64"
            />
            <button onClick={addDevice} disabled={!deviceName} className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50 text-sm">
              Add Device
            </button>
          </div>
          {devices.length === 0 ? (
            <EmptyState title="No devices in this network" description="Add a device or create a pre-auth key for enrollment." />
          ) : (
            <div className="bg-white rounded-lg shadow overflow-hidden border border-gray-200">
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">IP</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Enrollment</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Node-Owned</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Seen</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Handshake</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tags</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {devices.map((dev) => (
                      <tr key={dev.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm font-medium">
                          <button onClick={() => navigate(`/devices/${dev.id}`)} className="text-indigo-600 hover:text-indigo-800">
                            {dev.name}
                          </button>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-500 font-mono">{dev.ip_address || '-'}</td>
                        <td className="px-4 py-3">
                          <StatusBadge status={dev.is_active ? 'Active' : 'Inactive'} variant={dev.is_active ? 'green' : 'red'} />
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={dev.enrollment_status} />
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-500">{dev.is_node_owned ? 'Yes' : 'No'}</td>
                        <td className="px-4 py-3 text-sm text-gray-500">
                          {dev.last_seen_at ? new Date(dev.last_seen_at).toLocaleString() : 'Never'}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-500">
                          {dev.last_handshake ? new Date(dev.last_handshake).toLocaleString() : '-'}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-500">{(dev.tags || []).join(', ') || '-'}</td>
                        <td className="px-4 py-3">
                          {dev.is_active && dev.enrollment_status === 'active' && (
                            <button onClick={() => handleRevoke(dev.id)} className="text-xs text-red-600 hover:text-red-800">Revoke</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'topology' && (
        <div className="space-y-6">
          <SectionCard title="Topology Configuration" subtitle={`Current: ${network.topology || 'star (default)'}`}>
            <div className="flex gap-2">
              {['star', 'mesh', 'hybrid'].map(t => (
                <button
                  key={t}
                  onClick={() => handleTopologyChange(t)}
                  className={`px-4 py-2 rounded text-sm border ${(network.topology || 'star') === t ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}`}
                >
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          </SectionCard>

          <SectionCard title="Topology Graph">
            {devices.length === 0 ? (
              <EmptyState title="No devices to display" />
            ) : (
              <TopologyGraph
                devices={devices.map(d => ({
                  id: d.id,
                  name: d.name,
                  is_active: d.is_active,
                  is_server: d.name === '__midscale_server__',
                }))}
                links={topologyLinks}
                onSelectDevice={(id) => navigate(`/devices/${id}`)}
              />
            )}
          </SectionCard>
        </div>
      )}

      {tab === 'acls' && (
        <div className="space-y-4">
          <p className="text-sm text-gray-500">Default-deny ACL rules control traffic between tagged devices.</p>
          {acls.length === 0 ? (
            <EmptyState title="No ACL rules" description="All traffic is allowed when no rules exist." />
          ) : (
            <div className="bg-white rounded-lg shadow overflow-hidden border border-gray-200">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Priority</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source Tags</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Dest Tags</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {acls.map((rule) => (
                    <tr key={rule.id}>
                      <td className="px-4 py-3">{rule.priority}</td>
                      <td className="px-4 py-3 text-sm">{rule.src_tags.join(', ') || '*'}</td>
                      <td className="px-4 py-3 text-sm">{rule.dst_tags.join(', ') || '*'}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={rule.action} variant={rule.action === 'allow' ? 'green' : 'red'} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'dns' && (
        <div className="space-y-4">
          <p className="text-sm text-gray-500">DNS entries are served to devices that have DNS enabled.</p>
          {dns.length === 0 ? (
            <EmptyState title="No DNS entries" />
          ) : (
            <div className="bg-white rounded-lg shadow overflow-hidden border border-gray-200">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Domain</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Address</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {dns.map((entry) => (
                    <tr key={entry.id}>
                      <td className="px-4 py-3 text-sm">{entry.domain}</td>
                      <td className="px-4 py-3 text-sm text-gray-500 font-mono">{entry.address}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'keys' && (
        <div className="space-y-4">
          <SectionCard title="Generate Pre-auth Key">
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Expires (hours)</label>
                <input
                  type="number"
                  value={keyExpiry}
                  onChange={(e) => setKeyExpiry(e.target.value)}
                  className="rounded border border-gray-300 px-3 py-2 text-sm w-24"
                  min="1"
                />
              </div>
              <div className="flex items-center gap-2 pb-1">
                <input
                  type="checkbox"
                  id="keyReusable"
                  checked={keyReusable}
                  onChange={(e) => setKeyReusable(e.target.checked)}
                  className="rounded"
                />
                <label htmlFor="keyReusable" className="text-sm text-gray-700">Reusable</label>
              </div>
              <div className="flex-1 min-w-[200px]">
                <label className="block text-xs text-gray-500 mb-1">Server URL (for enrollment command)</label>
                <input
                  type="text"
                  value={serverUrl}
                  onChange={(e) => setServerUrl(e.target.value)}
                  className="rounded border border-gray-300 px-3 py-2 text-sm w-full"
                  placeholder="https://midscale.example.com"
                />
              </div>
              <button onClick={createKey} className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 text-sm">
                Generate
              </button>
            </div>
          </SectionCard>

          {keys.length === 0 ? (
            <EmptyState
              title="No pre-auth keys yet"
              description="Create one to enroll your first device."
              action={{ label: 'Generate Key', onClick: createKey }}
            />
          ) : (
            <div className="space-y-3">
              {keys.map((k) => {
                const enrollCmd = `midscaled enroll --server ${serverUrl} --preauth-key "${k.key}" --name <device-name> --apply`
                return (
                  <div key={k.id} className="bg-white rounded-lg shadow border border-gray-200 p-4">
                    <div className="flex items-start justify-between">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <code className="text-sm bg-gray-100 px-2 py-1 rounded">{k.key.slice(0, 32)}…</code>
                          <CopyButton text={k.key} label="Copy Key" />
                        </div>
                        <div className="flex items-center gap-3 text-xs text-gray-500">
                          <span>{k.reusable ? 'Reusable' : 'One-time'}</span>
                          <span>Expires: {new Date(k.expires_at).toLocaleString()}</span>
                        </div>
                      </div>
                      <button onClick={() => deleteKey(k.id)} className="text-xs text-red-600 hover:text-red-800">Delete</button>
                    </div>
                    <div className="mt-2">
                      <p className="text-xs text-gray-500 mb-1">Enrollment command:</p>
                      <div className="bg-gray-900 text-green-400 p-2 rounded text-xs font-mono overflow-x-auto whitespace-nowrap">
                        {enrollCmd}
                      </div>
                      <div className="mt-1">
                        <CopyButton text={enrollCmd} label="Copy Command" />
                      </div>
                    </div>
                    {serverUrl.includes('localhost') && (
                      <p className="text-xs text-yellow-600 mt-2">Warning: server URL is localhost. Add <code className="bg-yellow-100 px-1">--insecure</code> for local dev.</p>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {tab === 'routes' && (
        <div className="space-y-4">
          <p className="text-sm text-gray-500">Advertised routes for this network.</p>
          {routes.length === 0 ? (
            <EmptyState title="No routes advertised" description="Routes appear here when devices advertise them." />
          ) : (
            <div className="bg-white rounded-lg shadow overflow-hidden border border-gray-200">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Prefix</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Device</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Exit Node</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Approved</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Enabled</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {routes.map((r) => {
                    const dev = devices.find(d => d.id === r.device_id)
                    return (
                      <tr key={r.id}>
                        <td className="px-4 py-3 text-sm font-mono">{r.prefix}</td>
                        <td className="px-4 py-3 text-sm text-gray-500">{dev?.name || r.device_id.slice(0, 8)}</td>
                        <td className="px-4 py-3">
                          {r.is_exit_node ? <StatusBadge status="Exit Node" variant="blue" /> : '-'}
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={r.approved ? 'Approved' : 'Pending'} variant={r.approved ? 'green' : 'yellow'} />
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={r.enabled ? 'Enabled' : 'Disabled'} variant={r.enabled ? 'green' : 'red'} />
                        </td>
                        <td className="px-4 py-3 flex gap-2">
                          {!r.approved && (
                            <button onClick={() => handleApproveRoute(r.id)} className="text-xs bg-green-600 text-white px-2 py-1 rounded hover:bg-green-700">Approve</button>
                          )}
                          <button onClick={() => handleToggleRoute(r.id, !r.enabled)} className="text-xs bg-gray-600 text-white px-2 py-1 rounded hover:bg-gray-700">
                            {r.enabled ? 'Disable' : 'Enable'}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'activity' && (
        <div className="space-y-4">
          <p className="text-sm text-gray-500">Recent audit events for this network.</p>
          {audit.length === 0 ? (
            <EmptyState title="No recent activity" />
          ) : (
            <div className="bg-white rounded-lg shadow overflow-hidden border border-gray-200">
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actor</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Target</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">IP</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {audit.map((entry) => (
                      <tr key={entry.id}>
                        <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{new Date(entry.created_at).toLocaleString()}</td>
                        <td className="px-4 py-3 text-sm font-medium">{entry.action}</td>
                        <td className="px-4 py-3 text-sm text-gray-500">{entry.actor_id?.slice(0, 8) || 'system'}</td>
                        <td className="px-4 py-3 text-sm text-gray-500">{entry.target_type ? `${entry.target_type}:${entry.target_id?.slice(0, 8)}` : '-'}</td>
                        <td className="px-4 py-3 text-sm text-gray-500 font-mono">{entry.ip_address || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
