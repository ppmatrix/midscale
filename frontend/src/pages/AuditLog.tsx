import { useEffect, useState } from 'react'
import { auditApi, type AuditLogEntry } from '../api/networks'
import { useAuth } from '../hooks/useAuth'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'

const ACTIONS = [
  '', 'auth.login', 'auth.register', 'network.create', 'network.update', 'network.delete',
  'device.create', 'device.enroll', 'device.revoke', 'device.update',
  'preauth_key.create', 'preauth_key.delete',
  'acl.create', 'acl.update', 'acl.delete',
  'dns.create', 'dns.delete',
  'route.advertise', 'route.approve', 'route.update',
]

export default function AuditLog() {
  const { token } = useAuth()
  const [entries, setEntries] = useState<AuditLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [skip, setSkip] = useState(0)
  const [filterAction, setFilterAction] = useState('')
  const [filterActor, setFilterActor] = useState('')
  const limit = 50

  const fetchLogs = (newSkip = 0) => {
    setLoading(true)
    const params: Record<string, string | number> = { skip: newSkip, limit }
    if (filterAction) params.action = filterAction
    if (filterActor) params.actor_id = filterActor
    auditApi.list(params as Parameters<typeof auditApi.list>[0])
      .then((page) => {
        setEntries(page.items)
        setTotal(page.total)
        setSkip(newSkip)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchLogs()
  }, [filterAction, filterActor])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Audit Log</h1>
        <p className="text-sm text-gray-500 mt-1">Track all mutations across the system.</p>
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Action</label>
          <select
            value={filterAction}
            onChange={(e) => { setFilterAction(e.target.value); setSkip(0) }}
            className="rounded border border-gray-300 px-3 py-1.5 text-sm"
          >
            <option value="">All Actions</option>
            {ACTIONS.filter(Boolean).map(a => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Actor ID</label>
          <input
            type="text"
            value={filterActor}
            onChange={(e) => { setFilterActor(e.target.value); setSkip(0) }}
            placeholder="UUID prefix…"
            className="rounded border border-gray-300 px-3 py-1.5 text-sm"
          />
        </div>
        <div className="pt-4">
          <span className="text-sm text-gray-500">{total} total entries</span>
        </div>
      </div>

      {loading ? (
        <LoadingSpinner />
      ) : entries.length === 0 ? (
        <EmptyState title="No audit entries" description={filterAction || filterActor ? 'Try different filters.' : 'No mutations have been recorded yet.'} />
      ) : (
        <>
          <div className="bg-white rounded-lg shadow overflow-hidden border border-gray-200">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Timestamp</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actor</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Target Type</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Target ID</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">IP</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {entries.map((entry) => (
                    <tr key={entry.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{new Date(entry.created_at).toLocaleString()}</td>
                      <td className="px-4 py-3 text-sm font-medium">{entry.action}</td>
                      <td className="px-4 py-3 text-sm text-gray-500 font-mono">{entry.actor_id?.slice(0, 12) || 'system'}</td>
                      <td className="px-4 py-3 text-sm text-gray-500">{entry.target_type || '-'}</td>
                      <td className="px-4 py-3 text-sm text-gray-500 font-mono">{entry.target_id?.slice(0, 12) || '-'}</td>
                      <td className="px-4 py-3 text-sm text-gray-500 font-mono">{entry.ip_address || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex justify-between items-center">
            <button
              onClick={() => fetchLogs(Math.max(0, skip - limit))}
              disabled={skip === 0}
              className="px-3 py-1.5 text-sm bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
            >
              Previous
            </button>
            <span className="text-sm text-gray-500">
              Showing {skip + 1}–{Math.min(skip + limit, total)} of {total}
            </span>
            <button
              onClick={() => fetchLogs(skip + limit)}
              disabled={skip + limit >= total}
              className="px-3 py-1.5 text-sm bg-white border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </>
      )}

      {!token && (
        <div className="bg-yellow-50 text-yellow-700 p-3 rounded text-sm border border-yellow-200">
          You must be logged in to view audit logs.
        </div>
      )}
    </div>
  )
}
