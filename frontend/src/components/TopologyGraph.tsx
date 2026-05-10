import { useMemo } from 'react'

interface TopologyDevice {
  id: string
  name: string
  is_active: boolean
  is_server?: boolean
}

interface TopologyLink {
  source_id: string
  target_id: string
  type: 'direct' | 'relay' | 'hub' | 'offline'
}

interface TopologyGraphProps {
  devices: TopologyDevice[]
  links: TopologyLink[]
  selectedDeviceId?: string | null
  onSelectDevice?: (id: string) => void
}

const COLORS = {
  direct: '#22c55e',
  relay: '#f97316',
  hub: '#3b82f6',
  offline: '#9ca3af',
}

const RADIUS = 140
const CENTER = 200

export default function TopologyGraph({ devices, links, selectedDeviceId, onSelectDevice }: TopologyGraphProps) {
  const positions = useMemo(() => {
    const server = devices.find(d => d.is_server)
    const clients = devices.filter(d => !d.is_server)

    const pos: Record<string, { x: number; y: number }> = {}

    if (server) {
      pos[server.id] = { x: CENTER, y: CENTER }
    } else {
      pos['__hub__'] = { x: CENTER, y: CENTER }
    }

    clients.forEach((d, i) => {
      const angle = (2 * Math.PI * i) / clients.length - Math.PI / 2
      pos[d.id] = {
        x: CENTER + RADIUS * Math.cos(angle),
        y: CENTER + RADIUS * Math.sin(angle),
      }
    })

    return pos
  }, [devices])

  const viewBox = `0 0 ${CENTER * 2} ${CENTER * 2}`

  return (
    <div className="w-full flex flex-col items-center">
      <svg viewBox={viewBox} className="w-full max-w-md" style={{ height: CENTER * 2 }}>
        {links.map((link, i) => {
          const from = positions[link.source_id]
          const to = positions[link.target_id]
          if (!from || !to) return null
          const color = COLORS[link.type]
          const isDirect = link.type === 'direct'
          const isSelectedLink =
            selectedDeviceId && (link.source_id === selectedDeviceId || link.target_id === selectedDeviceId)
          return (
            <line
              key={i}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={color}
              strokeWidth={isSelectedLink ? 3 : 2}
              strokeDasharray={isDirect ? 'none' : '6,3'}
              opacity={isSelectedLink ? 1 : 0.6}
            />
          )
        })}

        {devices.map((d) => {
          const pos = positions[d.id]
          if (!pos) return null
          const isServer = d.is_server
          const isSelected = selectedDeviceId === d.id
          const r = isServer ? 18 : 12
          const fill = d.is_active ? (isServer ? '#6366f1' : '#374151') : '#d1d5db'
          return (
            <g
              key={d.id}
              onClick={() => onSelectDevice?.(d.id)}
              className={onSelectDevice ? 'cursor-pointer' : ''}
            >
              <circle
                cx={pos.x}
                cy={pos.y}
                r={r}
                fill={fill}
                stroke={isSelected ? '#6366f1' : 'none'}
                strokeWidth={isSelected ? 3 : 0}
              />
              <text
                x={pos.x}
                y={pos.y + r + 14}
                textAnchor="middle"
                fontSize="10"
                fill={isSelected ? '#6366f1' : '#6b7280'}
                className="select-none"
              >
                {d.name.length > 12 ? d.name.slice(0, 11) + '…' : d.name}
              </text>
            </g>
          )
        })}
      </svg>

      <div className="flex gap-4 mt-2 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-green-500 inline-block" /> Direct
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-orange-500 inline-block border-dashed" style={{ borderTop: '2px dashed #f97316', height: 0 }} /> Relay
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-blue-500 inline-block" /> Hub
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-gray-400 inline-block" /> Offline
        </span>
      </div>
    </div>
  )
}
