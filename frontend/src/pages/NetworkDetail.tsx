import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { networksApi, type Network, type Device, type PreAuthKey, type ACLRule, type DNSEntry } from '../api/networks'

type Tab = 'devices' | 'acls' | 'dns' | 'keys'

export default function NetworkDetail() {
  const { networkId } = useParams<{ networkId: string }>()
  const navigate = useNavigate()
  const [network, setNetwork] = useState<Network | null>(null)
  const [devices, setDevices] = useState<Device[]>([])
  const [acls, setAcls] = useState<ACLRule[]>([])
  const [dns, setDns] = useState<DNSEntry[]>([])
  const [keys, setKeys] = useState<PreAuthKey[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<Tab>('devices')
  const [deviceName, setDeviceName] = useState('')

  useEffect(() => {
    if (!networkId) return
    Promise.all([
      networksApi.get(networkId),
      networksApi.listDevices(networkId),
      networksApi.listACLs(networkId),
      networksApi.listDNS(networkId),
      networksApi.listPreAuthKeys(networkId),
    ]).then(([net, devs, aclList, dnsList, keyList]) => {
      setNetwork(net)
      setDevices(devs)
      setAcls(aclList)
      setDns(dnsList)
      setKeys(keyList)
    }).catch(() => navigate('/'))
    .finally(() => setLoading(false))
  }, [networkId, navigate])

  const addDevice = async () => {
    if (!networkId || !deviceName) return
    try {
      const dev = await networksApi.createDevice(networkId, { name: deviceName })
      setDevices([...devices, dev])
      setDeviceName('')
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to create device')
    }
  }

  const createKey = async () => {
    if (!networkId) return
    try {
      const key = await networksApi.createPreAuthKey(networkId, {})
      setKeys([...keys, key])
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to create key')
    }
  }

  if (loading || !network) {
    return <p className="text-gray-500">Loading...</p>
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'devices', label: `Devices (${devices.length})` },
    { key: 'acls', label: `ACLs (${acls.length})` },
    { key: 'dns', label: `DNS (${dns.length})` },
    { key: 'keys', label: `Pre-auth Keys (${keys.length})` },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{network.name}</h1>
        <p className="text-gray-500">{network.subnet} &middot; {network.description || 'No description'}</p>
      </div>

      <div className="border-b border-gray-200">
        <div className="flex gap-4">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`pb-2 px-1 text-sm font-medium border-b-2 ${tab === t.key ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
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
              className="rounded border border-gray-300 px-3 py-2 w-64"
            />
            <button onClick={addDevice} disabled={!deviceName} className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700 disabled:opacity-50">
              Add Device
            </button>
          </div>
          {devices.length === 0 ? (
            <p className="text-gray-400">No devices in this network.</p>
          ) : (
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">IP</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tags</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {devices.map((dev) => (
                    <tr key={dev.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => navigate(`/devices/${dev.id}`)}>
                      <td className="px-6 py-4">{dev.name}</td>
                      <td className="px-6 py-4 text-sm text-gray-500">{dev.ip_address || '-'}</td>
                      <td className="px-6 py-4">
                        <span className={`px-2 py-1 rounded text-xs ${dev.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                          {dev.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500">{(dev.tags || []).join(', ') || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'acls' && (
        <div className="space-y-4">
          <p className="text-sm text-gray-500">Default-deny ACL rules control traffic between tagged devices.</p>
          {acls.length === 0 ? (
            <p className="text-gray-400">No ACL rules. All traffic is allowed.</p>
          ) : (
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Priority</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source Tags</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Dest Tags</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {acls.map((rule) => (
                    <tr key={rule.id}>
                      <td className="px-6 py-4">{rule.priority}</td>
                      <td className="px-6 py-4 text-sm">{rule.src_tags.join(', ') || '*'}</td>
                      <td className="px-6 py-4 text-sm">{rule.dst_tags.join(', ') || '*'}</td>
                      <td className="px-6 py-4">
                        <span className={`px-2 py-1 rounded text-xs ${rule.action === 'allow' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                          {rule.action}
                        </span>
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
            <p className="text-gray-400">No DNS entries.</p>
          ) : (
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Domain</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Address</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {dns.map((entry) => (
                    <tr key={entry.id}>
                      <td className="px-6 py-4">{entry.domain}</td>
                      <td className="px-6 py-4 text-sm text-gray-500">{entry.address}</td>
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
          <button onClick={createKey} className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700">
            Generate Pre-auth Key
          </button>
          {keys.length === 0 ? (
            <p className="text-gray-400">No pre-auth keys. Devices can still be created from the dashboard.</p>
          ) : (
            <div className="bg-white rounded-lg shadow overflow-hidden">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Key</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Reusable</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Expires</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {keys.map((k) => (
                    <tr key={k.id}>
                      <td className="px-6 py-4 text-sm font-mono">{k.key.slice(0, 32)}...</td>
                      <td className="px-6 py-4">{k.reusable ? 'Yes' : 'No'}</td>
                      <td className="px-6 py-4 text-sm text-gray-500">{new Date(k.expires_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
