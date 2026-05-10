import { useEffect, useState } from 'react'
import { healthApi, metricsApi } from '../api/networks'
import type { HealthSummary } from '../api/networks'
import StatusBadge from '../components/StatusBadge'
import SectionCard from '../components/SectionCard'
import MetricCard from '../components/MetricCard'
import LoadingSpinner from '../components/LoadingSpinner'

interface ProbeResult {
  healthy: boolean
  checks?: Record<string, { healthy: boolean; message: string }>
}

interface ParsedMetrics {
  devices_total: number
  devices_online: number
  relay_sessions_total: number
  nat_punch_total: number
  endpoint_probe_total: number
  websocket_connections: number
  controller_errors_total: number
}

export default function SystemHealth() {
  const [health, setHealth] = useState<HealthSummary | null>(null)
  const [live, setLive] = useState<ProbeResult | null>(null)
  const [ready, setReady] = useState<ProbeResult | null>(null)
  const [startup, setStartup] = useState<ProbeResult | null>(null)
  const [metrics, setMetrics] = useState<ParsedMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchAll = () => {
    setError('')
    Promise.all([
      healthApi.summary(),
      healthApi.live().catch(() => ({ healthy: false } as ProbeResult)),
      healthApi.ready().catch(() => ({ healthy: false } as ProbeResult)),
      healthApi.startup().catch(() => ({ healthy: false } as ProbeResult)),
      metricsApi.get().then(parseMetrics).catch(() => null),
    ]).then(([h, l, r, s, m]) => {
      setHealth(h)
      setLive(l as ProbeResult)
      setReady(r as ProbeResult)
      setStartup(s as ProbeResult)
      setMetrics(m)
    }).catch((err) => {
      setError(err instanceof Error ? err.message : 'Failed to load health data')
    }).finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 15000)
    return () => clearInterval(interval)
  }, [])

  if (loading) return <LoadingSpinner />

  return (
    <div className="space-y-6">
      {error && <div className="bg-red-50 text-red-700 p-3 rounded text-sm border border-red-200">{error}</div>}

      <div>
        <h1 className="text-2xl font-bold">System Health</h1>
        <p className="text-sm text-gray-500 mt-1">Backend status, probes, and key metrics.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Live"
          value={live?.healthy ? 'OK' : 'FAIL'}
          icon="♥"
          color={live?.healthy ? '#22c55e' : '#ef4444'}
        />
        <MetricCard
          title="Ready"
          value={ready?.healthy ? 'OK' : 'DEGRADED'}
          icon="●"
          color={ready?.healthy ? '#22c55e' : '#f97316'}
        />
        <MetricCard
          title="Startup"
          value={startup?.healthy ? 'OK' : 'FAIL'}
          icon="⚡"
          color={startup?.healthy ? '#22c55e' : '#ef4444'}
        />
        <MetricCard
          title="WG Controller"
          value={health?.wg_controller?.running ? 'Running' : 'Stopped'}
          icon="▦"
          color={health?.wg_controller?.running ? '#22c55e' : '#ef4444'}
        />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard title="Devices Total" value={metrics?.devices_total ?? '-'} icon="⚙" color="#6366f1" />
        <MetricCard title="Devices Online" value={metrics?.devices_online ?? '-'} subtitle={metrics ? `${Math.round((metrics.devices_online / (metrics.devices_total || 1)) * 100)}%` : ''} icon="●" color="#22c55e" />
        <MetricCard title="Relay Sessions" value={metrics?.relay_sessions_total ?? '-'} icon="↔" color="#f97316" />
        <MetricCard title="NAT Punches" value={metrics?.nat_punch_total ?? '-'} icon="⇄" color="#3b82f6" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard title="Endpoint Probes" value={metrics?.endpoint_probe_total ?? '-'} icon="◎" color="#8b5cf6" />
        <MetricCard title="WS Connections" value={metrics?.websocket_connections ?? '-'} icon="◉" color="#06b6d4" />
        <MetricCard title="Controller Errors" value={metrics?.controller_errors_total ?? '-'} icon="⚠" color="#ef4444" />
        <MetricCard title="STUN Server" value={health?.stun?.running ? 'Running' : 'Stopped'} subtitle={`Port ${health?.stun?.port || '-'}`} icon="◈" color={health?.stun?.running ? '#22c55e' : '#ef4444'} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <SectionCard title="Liveness Probe">
          {live?.healthy !== undefined ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <StatusBadge status={live.healthy ? 'Pass' : 'Fail'} variant={live.healthy ? 'green' : 'red'} />
                <span className="text-sm text-gray-600">Application running</span>
              </div>
            </div>
          ) : <p className="text-sm text-gray-400">No data</p>}
        </SectionCard>

        <SectionCard title="Readiness Probe">
          {ready?.checks ? (
            <div className="space-y-2">
              {Object.entries(ready.checks).map(([key, check]) => (
                <div key={key} className="flex items-center justify-between text-sm">
                  <span className="text-gray-600 capitalize">{key.replace(/_/g, ' ')}</span>
                  <StatusBadge status={check.healthy ? 'OK' : 'FAIL'} variant={check.healthy ? 'green' : 'red'} />
                </div>
              ))}
            </div>
          ) : <p className="text-sm text-gray-400">No data</p>}
        </SectionCard>

        <SectionCard title="Startup Probe">
          {startup?.checks ? (
            <div className="space-y-2">
              {Object.entries(startup.checks).map(([key, check]) => (
                <div key={key} className="flex items-center justify-between text-sm">
                  <span className="text-gray-600 capitalize">{key.replace(/_/g, ' ')}</span>
                  <StatusBadge status={check.healthy ? 'OK' : 'FAIL'} variant={check.healthy ? 'green' : 'red'} />
                </div>
              ))}
            </div>
          ) : <p className="text-sm text-gray-400">No data</p>}
        </SectionCard>
      </div>

      <SectionCard title="Services Summary">
        {health ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <ServiceItem label="WireGuard Controller" status={health.wg_controller?.running ? 'Running' : 'Stopped'} healthy={health.wg_controller?.running} />
            <ServiceItem label="STUN Server" status={health.stun?.running ? 'Running' : 'Stopped'} healthy={health.stun?.running} detail={`Port ${health.stun?.port || '-'}`} />
            <ServiceItem label="Relay Server" status={health.relay?.running ? 'Running' : 'Stopped'} healthy={health.relay?.running} detail={`Port ${health.relay?.port || '-'}`} />
            <ServiceItem label="WebSocket" status={`${health.websocket?.active_connections || 0} active`} healthy={true} />
          </div>
        ) : <p className="text-sm text-gray-400">No health data</p>}
      </SectionCard>
    </div>
  )
}

function ServiceItem({ label, status, healthy, detail }: { label: string; status: string; healthy?: boolean; detail?: string }) {
  return (
    <div className="bg-gray-50 rounded p-3">
      <p className="text-xs text-gray-500">{label}</p>
      <div className="flex items-center gap-2 mt-1">
        <StatusBadge status={healthy ? 'OK' : 'FAIL'} variant={healthy ? 'green' : 'red'} />
        <span className="text-sm font-medium">{status}</span>
      </div>
      {detail && <p className="text-xs text-gray-400 mt-0.5">{detail}</p>}
    </div>
  )
}

function parseMetrics(text: string): ParsedMetrics {
  const lines = text.split('\n')
  const get = (name: string): number => {
    for (const line of lines) {
      if (line.startsWith(name) && !line.startsWith('#')) {
        const parts = line.split(' ')
        return parseInt(parts[parts.length - 1], 10) || 0
      }
    }
    return 0
  }
  return {
    devices_total: get('midscale_devices_total'),
    devices_online: get('midscale_devices_online'),
    relay_sessions_total: get('midscale_relay_sessions_total'),
    nat_punch_total: get('midscale_nat_punch_total'),
    endpoint_probe_total: get('midscale_endpoint_probe_total'),
    websocket_connections: get('midscale_websocket_connections'),
    controller_errors_total: get('midscale_controller_errors_total'),
  }
}
