import { useEffect, useState, useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { networksApi, devicesApi, healthApi, type Network, type Device, type HealthSummary } from '../api/networks'
import { useAuth } from '../hooks/useAuth'
import MetricCard from '../components/MetricCard'
import StatusBadge from '../components/StatusBadge'
import EmptyState from '../components/EmptyState'
import LoadingSpinner from '../components/LoadingSpinner'

export default function Dashboard() {
  const { user } = useAuth()
  const isSuperuser = user?.is_superuser ?? false
  const navigate = useNavigate()
  const [networks, setNetworks] = useState<Network[]>([])
  const [devices, setDevices] = useState<Device[]>([])
  const [health, setHealth] = useState<HealthSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newSubnet, setNewSubnet] = useState('10.0.0.0/24')
  const [newDesc, setNewDesc] = useState('')
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<'name' | 'devices'>('name')

  const fetchData = () => {
    setError('')
    const promises: Promise<unknown>[] = [
      networksApi.list(),
      devicesApi.list(),
    ]
    if (isSuperuser) {
      promises.push(healthApi.summary().catch(() => null))
    }
    Promise.all(promises).then(([nets, devs, h]) => {
      setNetworks(nets as Network[])
      setDevices(devs as Device[])
      setHealth(h as HealthSummary | null)
    }).catch((err) => {
      setError(err instanceof Error ? err.message : 'Failed to load data')
    }).finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchData()
  }, [isSuperuser])

  const onlineDevices = useMemo(() => devices.filter(d => d.is_active), [devices])
  const totalRelay = 0

  const handleCreate = async () => {
    try {
      const net = await networksApi.create({ name: newName, subnet: newSubnet, description: newDesc || undefined })
      setNetworks([...networks, net])
      setShowCreate(false)
      setNewName('')
      setNewSubnet('10.0.0.0/24')
      setNewDesc('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create network')
    }
  }

  const filteredNetworks = useMemo(() => {
    let result = networks
    if (search) {
      const q = search.toLowerCase()
      result = result.filter(n => n.name.toLowerCase().includes(q) || n.subnet.includes(q))
    }
    const deviceCounts: Record<string, number> = {}
    devices.forEach(d => {
      deviceCounts[d.network_id] = (deviceCounts[d.network_id] || 0) + 1
    })
    const onlineCounts: Record<string, number> = {}
    devices.forEach(d => {
      if (d.is_active) onlineCounts[d.network_id] = (onlineCounts[d.network_id] || 0) + 1
    })
    return [...result].sort((a, b) => {
      if (sortBy === 'devices') return (deviceCounts[b.id] || 0) - (deviceCounts[a.id] || 0)
      return a.name.localeCompare(b.name)
    }).map(n => ({
      ...n,
      device_count: deviceCounts[n.id] || 0,
      online_count: onlineCounts[n.id] || 0,
    }))
  }, [networks, devices, search, sortBy])

  if (loading) return <LoadingSpinner />

  return (
    <div className="space-y-6">
      {error && (
        <div className="bg-red-50 text-red-700 p-3 rounded text-sm border border-red-200">{error}</div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard title="Networks" value={networks.length} icon="▦" color="#6366f1" />
        <MetricCard title="Total Devices" value={devices.length} icon="⚙" color="#374151" />
        <MetricCard title="Online" value={onlineDevices.length} subtitle={`${devices.length > 0 ? Math.round(onlineDevices.length / devices.length * 100) : 0}% online`} icon="●" color="#22c55e" />
        <MetricCard title="Backend" value={health?.status === 'ok' ? 'Healthy' : 'Unknown'} icon="♥" color={health?.status === 'ok' ? '#22c55e' : '#ef4444'} />
      </div>

      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">Networks</h1>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search networks..."
              className="rounded border border-gray-300 px-3 py-1.5 text-sm w-48"
            />
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as 'name' | 'devices')}
              className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            >
              <option value="name">Name</option>
              <option value="devices">Devices</option>
            </select>
          </div>
        </div>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 text-sm"
        >
          {showCreate ? 'Cancel' : '+ New Network'}
        </button>
      </div>

      {showCreate && (
        <div className="bg-white p-6 rounded-lg shadow space-y-4 border border-gray-200">
          <h2 className="text-lg font-semibold">Create Network</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Name</label>
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm"
                placeholder="My Network"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Subnet (CIDR)</label>
              <input
                type="text"
                value={newSubnet}
                onChange={(e) => setNewSubnet(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Description</label>
              <input
                type="text"
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm"
                placeholder="Optional"
              />
            </div>
          </div>
          <button
            onClick={handleCreate}
            disabled={!newName || !newSubnet}
            className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 disabled:opacity-50 text-sm"
          >
            Create
          </button>
        </div>
      )}

      {filteredNetworks.length === 0 ? (
        <EmptyState
          title={search ? 'No networks match your search' : 'No networks yet'}
          description={search ? 'Try a different search term' : 'Create one to get started.'}
          action={!search ? { label: 'Create Network', onClick: () => setShowCreate(true) } : undefined}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filteredNetworks.map((net: Network & { device_count?: number; online_count?: number }) => {
            const hasDevices = (net.device_count || 0) > 0
            const hasOnline = (net.online_count || 0) > 0
            return (
              <Link
                key={net.id}
                to={`/networks/${net.id}`}
                className="block bg-white p-5 rounded-lg shadow hover:shadow-md transition border border-gray-100"
              >
                <div className="flex items-start justify-between">
                  <h3 className="font-semibold text-lg">{net.name}</h3>
                  <div className="flex items-center gap-2">
                    {isSuperuser && net.owner_id && (
                      <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded">
                        Owned by {net.owner_id.slice(0, 8)}…
                      </span>
                    )}
                    {net.topology && (
                      <StatusBadge status={net.topology} variant={net.topology === 'mesh' ? 'blue' : net.topology === 'hybrid' ? 'orange' : 'green'} />
                    )}
                  </div>
                </div>
                <p className="text-sm text-gray-500 font-mono mt-1">{net.subnet}</p>
                {net.description && <p className="text-sm text-gray-400 mt-1">{net.description}</p>}
                <div className="flex items-center gap-3 mt-3 text-xs text-gray-500">
                  <span>{net.device_count || 0} devices</span>
                  {hasDevices && (
                    <span className={hasOnline ? 'text-green-600' : 'text-red-400'}>
                      {net.online_count || 0} online
                    </span>
                  )}
                </div>
                {!hasDevices && (
                  <div className="mt-2 text-xs text-yellow-600 bg-yellow-50 px-2 py-1 rounded">No devices</div>
                )}
              </Link>
            )
          })}
        </div>
      )}

      <section>
        <h2 className="text-xl font-semibold mb-3">All Devices ({devices.length})</h2>
        {devices.length === 0 ? (
          <EmptyState title="No devices registered" description="Devices appear here once enrolled." />
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
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Seen</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Network</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {devices.map((dev) => (
                    <tr
                      key={dev.id}
                      className="hover:bg-gray-50 cursor-pointer"
                      onClick={() => navigate(`/devices/${dev.id}`)}
                    >
                      <td className="px-4 py-3 text-sm font-medium">{dev.name}</td>
                      <td className="px-4 py-3 text-sm text-gray-500 font-mono">{dev.ip_address || '-'}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={dev.is_active ? 'Active' : 'Inactive'} variant={dev.is_active ? 'green' : 'red'} />
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={dev.enrollment_status} />
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500">
                        {dev.last_seen_at ? new Date(dev.last_seen_at).toLocaleString() : 'Never'}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-500">{dev.network_id.slice(0, 8)}…</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
