import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { devicesApi, type Device, type DeviceConfigV2 } from '../api/networks'
import StatusBadge from '../components/StatusBadge'
import SectionCard from '../components/SectionCard'
import LoadingSpinner from '../components/LoadingSpinner'
import CopyButton from '../components/CopyButton'

export default function DeviceDetail() {
  const { deviceId } = useParams<{ deviceId: string }>()
  const navigate = useNavigate()
  const [device, setDevice] = useState<Device | null>(null)
  const [configV2, setConfigV2] = useState<DeviceConfigV2 | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [configText, setConfigText] = useState<string | null>(null)
  const [showConfigV2, setShowConfigV2] = useState(false)

  useEffect(() => {
    if (!deviceId) return
    setError('')
    devicesApi.get(deviceId)
      .then(setDevice)
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load device')
        if (!device) navigate('/')
      })
      .finally(() => setLoading(false))
    devicesApi.getConfigV2(deviceId)
      .then(setConfigV2)
      .catch(() => {})
  }, [deviceId])

  const handleRotateKeys = async () => {
    if (!deviceId) return
    try {
      const updated = await devicesApi.rotateKeys(deviceId)
      if (typeof updated === 'object' && 'id' in updated) setDevice(updated as Device)
      alert('Keys rotated')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to rotate keys')
    }
  }

  const handleRotateToken = async () => {
    if (!deviceId) return
    try {
      const result = await devicesApi.rotateToken(deviceId)
      alert(`New token generated. It will be shown once: prefix=${result.device_token_prefix}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to rotate token')
    }
  }

  const handleRevoke = async () => {
    if (!deviceId) return
    try {
      const updated = await devicesApi.revoke(deviceId)
      setDevice(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revoke device')
    }
  }

  const handleGetConfig = async () => {
    if (!deviceId) return
    try {
      const res = await devicesApi.getConfig(deviceId)
      setConfigText(res.config)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get config')
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
      setError(err instanceof Error ? err.message : 'Failed to download config')
    }
  }

  const handleToggleActive = async () => {
    if (!deviceId || !device) return
    try {
      const updated = await devicesApi.update(deviceId, { is_active: !device.is_active })
      setDevice(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update device')
    }
  }

  if (loading || !device) return <LoadingSpinner />

  const primaryEndpoint = configV2?.peers
    ?.flatMap(p => p.endpoint_candidates)
    ?.find(c => c.preferred)

  const allEndpoints = configV2?.peers
    ?.flatMap(p => p.endpoint_candidates)
    || []

  const relayRequiredPeers = configV2?.peers?.filter(p => p.relay_required) || []

  return (
    <div className="space-y-6 max-w-4xl">
      {error && <div className="bg-red-50 text-red-700 p-3 rounded text-sm border border-red-200">{error}</div>}

      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">{device.name}</h1>
            <StatusBadge status={device.is_active ? 'Active' : 'Inactive'} variant={device.is_active ? 'green' : 'red'} />
            <StatusBadge status={device.enrollment_status} />
          </div>
          <p className="text-sm text-gray-500 mt-1">
            Device ID: {device.id.slice(0, 8)}…
            {device.is_node_owned && <span> &middot; Node-owned</span>}
            {device.ip_address && <span> &middot; {device.ip_address}</span>}
          </p>
        </div>
        <button onClick={() => navigate(`/networks/${device.network_id}`)} className="text-sm text-indigo-600 hover:text-indigo-800">
          View Network →
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SectionCard title="Overview">
          <div className="space-y-3">
            <Row label="Name" value={device.name} />
            <Row label="IP Address" value={device.ip_address || '-'} mono />
            <Row label="Status" value={<StatusBadge status={device.is_active ? 'Active' : 'Inactive'} />} />
            <Row label="Enrollment" value={<StatusBadge status={device.enrollment_status} />} />
            <Row label="Node-Owned" value={device.is_node_owned ? 'Yes (private key local)' : 'No (server-managed)'} />
            <Row label="Tags" value={(device.tags || []).join(', ') || 'None'} />
            <Row label="DNS Enabled" value={device.dns_enabled ? 'Yes' : 'No'} />
            <Row label="Created" value={new Date(device.created_at).toLocaleString()} />
            {device.enrolled_at && <Row label="Enrolled At" value={new Date(device.enrolled_at).toLocaleString()} />}
            {device.last_seen_at && <Row label="Last Seen" value={new Date(device.last_seen_at).toLocaleString()} />}
            {device.last_handshake && <Row label="Last Handshake" value={new Date(device.last_handshake).toLocaleString()} />}
            {device.exit_node_id && <Row label="Exit Node" value={<StatusBadge status="Exit Node" variant="blue" />} />}
          </div>
        </SectionCard>

        <SectionCard title="Security">
          <div className="space-y-3">
            <Row label="Public Key" value={device.public_key ? `${device.public_key.slice(0, 32)}…` : 'Not generated'} mono />
            <Row label="Token Prefix" value={device.device_token_prefix || 'N/A'} mono />
            <Row label="Enrollment Status" value={<StatusBadge status={device.enrollment_status} />} />
            {device.revoked_at && <Row label="Revoked At" value={new Date(device.revoked_at).toLocaleString()} />}
            <div className="flex flex-wrap gap-2 pt-2">
              <button onClick={handleRotateKeys} className="bg-yellow-600 text-white px-3 py-1.5 rounded hover:bg-yellow-700 text-sm">
                Rotate Keys
              </button>
              <button onClick={handleRotateToken} className="bg-orange-600 text-white px-3 py-1.5 rounded hover:bg-orange-700 text-sm">
                Rotate Token
              </button>
              {device.is_active && device.enrollment_status !== 'revoked' && (
                <button onClick={handleRevoke} className="bg-red-600 text-white px-3 py-1.5 rounded hover:bg-red-700 text-sm">
                  Revoke Device
                </button>
              )}
              <button onClick={handleToggleActive} className={`px-3 py-1.5 rounded text-sm text-white ${device.is_active ? 'bg-red-600 hover:bg-red-700' : 'bg-green-600 hover:bg-green-700'}`}>
                {device.is_active ? 'Deactivate' : 'Activate'}
              </button>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Connectivity">
          <div className="space-y-3">
            <Row label="Connectivity" value={primaryEndpoint?.reachable ? <StatusBadge status="Direct" variant="green" /> : relayRequiredPeers.length > 0 ? <StatusBadge status="Relay" variant="orange" /> : <StatusBadge status="Unknown" variant="gray" />} />
            {primaryEndpoint && (
              <>
                <Row label="Preferred Endpoint" value={`${primaryEndpoint.endpoint}:${primaryEndpoint.port}`} mono />
                <Row label="Source" value={primaryEndpoint.source} />
                <Row label="Latency" value={primaryEndpoint.latency_ms ? `${primaryEndpoint.latency_ms}ms` : 'N/A'} />
                <Row label="Score" value={String(primaryEndpoint.score)} />
              </>
            )}
            <Row label="Peers reachable via relay" value={String(relayRequiredPeers.length)} />
          </div>
        </SectionCard>

        {configV2 && (
          <SectionCard title="Config v2">
            <div className="space-y-3">
              <Row label="Version" value={configV2.version} />
              <Row label="Revision" value={configV2.revision} mono />
              <Row label="Hash" value={configV2.hash.length > 24 ? `${configV2.hash.slice(0, 24)}…` : configV2.hash} mono />
              <Row label="Generated" value={new Date(configV2.generated_at).toLocaleString()} />
              <Row label="Address" value={configV2.interface.address || '-'} mono />
              <Row label="DNS" value={configV2.interface.dns?.join(', ') || 'None'} />
              <Row label="Peers" value={String(configV2.peers.length)} />
              <Row label="Routes" value={configV2.routes?.join(', ') || 'None'} />
              <div className="flex gap-2 pt-2">
                <button
                  onClick={() => setShowConfigV2(!showConfigV2)}
                  className="bg-indigo-600 text-white px-3 py-1.5 rounded hover:bg-indigo-700 text-sm"
                >
                  {showConfigV2 ? 'Hide JSON' : 'View JSON'}
                </button>
                <CopyButton text={JSON.stringify(configV2, null, 2)} label="Copy JSON" />
                <button onClick={handleGetConfig} className="bg-gray-600 text-white px-3 py-1.5 rounded hover:bg-gray-700 text-sm">
                  View v1 Config
                </button>
                <button onClick={handleDownloadConfig} className="bg-green-600 text-white px-3 py-1.5 rounded hover:bg-green-700 text-sm">
                  Download
                </button>
              </div>
            </div>
          </SectionCard>
        )}
      </div>

      {showConfigV2 && configV2 && (
        <div className="bg-gray-900 text-green-400 p-4 rounded-lg overflow-x-auto border border-gray-700">
          <pre className="text-xs whitespace-pre-wrap max-h-96 overflow-y-auto">{JSON.stringify(configV2, null, 2)}</pre>
        </div>
      )}

      {configText && (
        <SectionCard title="Config v1 (Legacy)">
          <div className="bg-gray-900 text-green-400 p-4 rounded-lg overflow-x-auto">
            <pre className="text-sm whitespace-pre-wrap">{configText}</pre>
          </div>
        </SectionCard>
      )}

      {allEndpoints.length > 0 && (
        <SectionCard title="Endpoint Candidates" subtitle={`${allEndpoints.length} candidate(s)`}>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Endpoint</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Port</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Local IP</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Public IP</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Reachable</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Latency</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Score</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Pref</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {allEndpoints.map((ep, i) => (
                  <tr key={i} className={ep.preferred ? 'bg-green-50' : ''}>
                    <td className="px-3 py-2 font-mono">{ep.endpoint}</td>
                    <td className="px-3 py-2">{ep.port}</td>
                    <td className="px-3 py-2">{ep.source}</td>
                    <td className="px-3 py-2 font-mono">{ep.local_ip || '-'}</td>
                    <td className="px-3 py-2 font-mono">{ep.public_ip || '-'}</td>
                    <td className="px-3 py-2"><StatusBadge status={ep.reachable ? 'Yes' : 'No'} variant={ep.reachable ? 'green' : 'red'} /></td>
                    <td className="px-3 py-2">{ep.latency_ms != null ? `${ep.latency_ms}ms` : '-'}</td>
                    <td className="px-3 py-2">{ep.score}</td>
                    <td className="px-3 py-2">{ep.preferred ? '★' : '○'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>
      )}

      {(relayRequiredPeers.length > 0 || (configV2?.peers?.some(p => p.relay_candidates && p.relay_candidates.length > 0))) && (
        <SectionCard title="Relay / NAT" subtitle="Relay fallback status">
          <div className="space-y-3">
            {relayRequiredPeers.length > 0 && (
              <div>
                <p className="text-sm font-medium mb-2">Relay-required peers:</p>
                <div className="flex flex-wrap gap-2">
                  {relayRequiredPeers.map((p, i) => (
                    <span key={i} className="text-xs bg-orange-100 text-orange-800 px-2 py-1 rounded">
                      {p.public_key.slice(0, 16)}…
                    </span>
                  ))}
                </div>
              </div>
            )}
            {configV2?.peers?.filter(p => p.relay_candidates?.length).map((p, i) => (
              <div key={i}>
                <p className="text-sm font-medium mb-1">Relay candidates for {p.public_key.slice(0, 16)}…:</p>
                {p.relay_candidates?.map((rc, j) => (
                  <div key={j} className="text-xs text-gray-600 bg-gray-50 px-2 py-1 rounded mb-1">
                    {rc.relay_node} @ {rc.relay_endpoint} ({rc.relay_region}) {rc.preferred ? '★' : ''}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </SectionCard>
      )}
    </div>
  )
}

function Row({ label, value, mono }: { label: string; value: string | number | React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex justify-between items-center text-sm">
      <span className="text-gray-500">{label}</span>
      <span className={`text-right max-w-[60%] break-all ${mono ? 'font-mono text-xs' : ''}`}>{value}</span>
    </div>
  )
}
