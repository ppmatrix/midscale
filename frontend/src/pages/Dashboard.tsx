import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { networksApi, type Network, type Device } from '../api/networks'
import { devicesApi } from '../api/devices'

export default function Dashboard() {
  const navigate = useNavigate()
  const [networks, setNetworks] = useState<Network[]>([])
  const [devices, setDevices] = useState<Device[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newSubnet, setNewSubnet] = useState('10.0.0.0/24')
  const [newDesc, setNewDesc] = useState('')

  useEffect(() => {
    Promise.all([
      networksApi.list(),
      devicesApi.list(),
    ]).then(([nets, devs]) => {
      setNetworks(nets)
      setDevices(devs)
    }).catch(() => {
      navigate('/login')
    }).finally(() => setLoading(false))
  }, [navigate])

  const handleCreate = async () => {
    try {
      const net = await networksApi.create({ name: newName, subnet: newSubnet, description: newDesc || undefined })
      setNetworks([...networks, net])
      setShowCreate(false)
      setNewName('')
      setNewSubnet('10.0.0.0/24')
      setNewDesc('')
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to create network')
    }
  }

  if (loading) {
    return <p className="text-gray-500">Loading...</p>
  }

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700"
        >
          {showCreate ? 'Cancel' : 'New Network'}
        </button>
      </div>

      {showCreate && (
        <div className="bg-white p-6 rounded-lg shadow space-y-4">
          <h2 className="text-lg font-semibold">Create Network</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Name</label>
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2"
                placeholder="My Network"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Subnet (CIDR)</label>
              <input
                type="text"
                value={newSubnet}
                onChange={(e) => setNewSubnet(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2"
                placeholder="10.0.0.0/24"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Description</label>
              <input
                type="text"
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
                className="mt-1 block w-full rounded border border-gray-300 px-3 py-2"
                placeholder="Optional"
              />
            </div>
          </div>
          <button
            onClick={handleCreate}
            disabled={!newName || !newSubnet}
            className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 disabled:opacity-50"
          >
            Create
          </button>
        </div>
      )}

      <section>
        <h2 className="text-xl font-semibold mb-4">Networks ({networks.length})</h2>
        {networks.length === 0 ? (
          <p className="text-gray-400">No networks yet. Create one to get started.</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {networks.map((net) => (
              <Link
                key={net.id}
                to={`/networks/${net.id}`}
                className="block bg-white p-5 rounded-lg shadow hover:shadow-md transition"
              >
                <h3 className="font-semibold text-lg">{net.name}</h3>
                <p className="text-sm text-gray-500">{net.subnet}</p>
                {net.description && (
                  <p className="text-sm text-gray-400 mt-1">{net.description}</p>
                )}
              </Link>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-xl font-semibold mb-4">All Devices ({devices.length})</h2>
        {devices.length === 0 ? (
          <p className="text-gray-400">No devices registered.</p>
        ) : (
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">IP</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Network</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {devices.map((dev) => (
                  <tr
                    key={dev.id}
                    className="hover:bg-gray-50 cursor-pointer"
                    onClick={() => navigate(`/devices/${dev.id}`)}
                  >
                    <td className="px-6 py-4">{dev.name}</td>
                    <td className="px-6 py-4 text-sm text-gray-500">{dev.ip_address || '-'}</td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded text-xs ${dev.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                        {dev.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-500">{dev.network_id.slice(0, 8)}...</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
