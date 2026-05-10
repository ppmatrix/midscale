interface StatusBadgeProps {
  status: string
  variant?: 'green' | 'red' | 'yellow' | 'gray' | 'blue' | 'orange'
  label?: string
}

const colorClasses: Record<string, string> = {
  green: 'bg-green-100 text-green-800',
  red: 'bg-red-100 text-red-800',
  yellow: 'bg-yellow-100 text-yellow-800',
  gray: 'bg-gray-100 text-gray-600',
  blue: 'bg-blue-100 text-blue-800',
  orange: 'bg-orange-100 text-orange-800',
}

export default function StatusBadge({ status, variant, label }: StatusBadgeProps) {
  const color = variant || (() => {
    const s = status.toLowerCase()
    if (s === 'active' || s === 'online' || s === 'ok' || s === 'yes' || s === 'reachable' || s === 'direct') return 'green'
    if (s === 'inactive' || s === 'offline' || s === 'no' || s === 'revoked') return 'red'
    if (s === 'pending' || s === 'connecting') return 'yellow'
    if (s === 'relay') return 'orange'
    if (s === 'hub') return 'blue'
    return 'gray'
  })()

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colorClasses[color] || colorClasses.gray}`}>
      {label || status}
    </span>
  )
}
