import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { devicesApi } from '../api/devices'
import type { Device } from '../api/networks'

export default function DeviceDetail() {
  const { deviceId } = useParams<{ deviceId: string }>()
  const navigate = useNavigate()
  const [device, setDevice] = useState<Device | null>(null)
  const [loading, setLoading] = useState(true)
  const [config, setConfig] = useState<string | null>(null)

  useEffect(() => {
    if (!deviceId) return
    devicesApi.get(deviceId)
      .then(setDevice)
      .catch(() => navigate('/'))
      .finally(() => setLoading(false))
  }, [deviceId, navigate])

  const handleRotateKeys = async () => {
    if (!deviceId) return
    try {
      const updated = await devicesApi.rotateKeys(deviceId)
      setDevice(updated)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to rotate keys')
    }
  }

  const handleGetConfig = async () => {
    if (!deviceId) return
    try {
      const res = await devicesApi.getConfig(deviceId)
      setConfig(res.config)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to get config')
    }
  }

  const handleDownloadConfig = async () => {
    if (!deviceId) return
    try {
      const res = await devicesApi.getConfig(deviceId)
      const blob = new Blob([res.config], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = res.filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to download config')
    }
  }

  const handleToggleActive = async () => {
    if (!deviceId || !device) return
    try {
      const updated = await devicesApi.update(deviceId, { is_active: !device.is_active })
      setDevice(updated)
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to update device')
    }
  }

  if (loading || !device) {
    return <p className="text-gray-500">Loading...</p>
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold">{device.name}</h1>
          <p className="text-gray-500">Device ID: {device.id}</p>
        </div>
        <button
          onClick={() => navigate(`/networks/${device.network_id}`)}
          className="text-indigo-600 hover:text-indigo-800"
        >
          View Network
        </button>
      </div>

      <div className="bg-white rounded-lg shadow divide-y">
        <div className="px-6 py-4 flex justify-between">
          <span className="text-gray-500">IP Address</span>
          <span className="font-mono">{device.ip_address || '-'}</span>
        </div>
        <div className="px-6 py-4 flex justify-between">
          <span className="text-gray-500">Public Key</span>
          <span className="font-mono text-sm">{device.public_key ? device.public_key.slice(0, 32) + '...' : 'Not generated'}</span>
        </div>
        <div className="px-6 py-4 flex justify-between">
          <span className="text-gray-500">Status</span>
          <span className={`px-2 py-1 rounded text-xs ${device.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
            {device.is_active ? 'Active' : 'Inactive'}
          </span>
        </div>
        <div className="px-6 py-4 flex justify-between">
          <span className="text-gray-500">DNS Enabled</span>
          <span>{device.dns_enabled ? 'Yes' : 'No'}</span>
        </div>
        <div className="px-6 py-4 flex justify-between">
          <span className="text-gray-500">Tags</span>
          <span>{(device.tags || []).join(', ') || 'None'}</span>
        </div>
        <div className="px-6 py-4 flex justify-between">
          <span className="text-gray-500">Created</span>
          <span>{new Date(device.created_at).toLocaleString()}</span>
        </div>
        {device.last_handshake && (
          <div className="px-6 py-4 flex justify-between">
            <span className="text-gray-500">Last Handshake</span>
            <span>{new Date(device.last_handshake).toLocaleString()}</span>
          </div>
        )}
      </div>

      <div className="flex gap-3">
        <button onClick={handleRotateKeys} className="bg-yellow-600 text-white px-4 py-2 rounded hover:bg-yellow-700">
          Rotate Keys
        </button>
        <button onClick={handleGetConfig} className="bg-indigo-600 text-white px-4 py-2 rounded hover:bg-indigo-700">
          View Config
        </button>
        <button onClick={handleDownloadConfig} className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700">
          Download Config
        </button>
        <button onClick={handleToggleActive} className={`px-4 py-2 rounded text-white ${device.is_active ? 'bg-red-600 hover:bg-red-700' : 'bg-green-600 hover:bg-green-700'}`}>
          {device.is_active ? 'Deactivate' : 'Activate'}
        </button>
      </div>

      {config && (
        <div className="bg-gray-900 text-green-400 p-4 rounded-lg overflow-x-auto">
          <pre className="text-sm whitespace-pre-wrap">{config}</pre>
        </div>
      )}
    </div>
  )
}
