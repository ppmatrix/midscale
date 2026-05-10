interface MetricCardProps {
  title: string
  value: string | number
  subtitle?: string
  icon?: string
  trend?: 'up' | 'down' | 'neutral'
  color?: string
}

export default function MetricCard({ title, value, subtitle, icon, trend, color }: MetricCardProps) {
  return (
    <div className="bg-white rounded-lg shadow p-5 border-l-4" style={{ borderLeftColor: color || '#6366f1' }}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-gray-500">{title}</p>
          <p className="text-2xl font-bold mt-1">{value}</p>
          {subtitle && <p className="text-xs text-gray-400 mt-1">{subtitle}</p>}
        </div>
        {icon && <span className="text-2xl opacity-60">{icon}</span>}
      </div>
      {trend && (
        <div className="mt-2">
          <span className={`text-xs ${trend === 'up' ? 'text-green-600' : trend === 'down' ? 'text-red-600' : 'text-gray-400'}`}>
            {trend === 'up' ? '↑' : trend === 'down' ? '↓' : '→'} {trend}
          </span>
        </div>
      )}
    </div>
  )
}
