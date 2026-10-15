import {
  BarChart, Bar,
  LineChart, Line,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts'

const CHART_COLORS = [
  '#14b8a6', '#06b6d4', '#8b5cf6', '#f59e0b',
  '#ef4444', '#10b981', '#3b82f6', '#ec4899',
  '#6366f1', '#84cc16',
]

const tooltipStyle = {
  backgroundColor: '#1a2332',
  border: '1px solid rgba(148, 163, 184, 0.2)',
  borderRadius: '8px',
  color: '#f1f5f9',
  fontSize: '0.8rem',
  boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
}

/**
 * Renders the appropriate chart type (bar, line, pie) based on config.
 */
function ChartRenderer({ chart, data }) {
  if (!chart || !data?.columns || !data?.rows) return null

  // Transform row data into chart-friendly format
  const chartData = transformData(data, chart)
  if (!chartData || chartData.length === 0) return null

  return (
    <div className="chart-container">
      <div className="chart-title">{chart.title || 'Chart'}</div>
      <ResponsiveContainer width="100%" height={300}>
        {renderChart(chart, chartData)}
      </ResponsiveContainer>
    </div>
  )
}

function transformData(data, chart) {
  const { columns, rows } = data
  const xIdx = columns.indexOf(chart.x || chart.nameKey)
  const yIdx = columns.indexOf(chart.y || chart.dataKey)

  if (xIdx === -1 && yIdx === -1) return null

  return rows.slice(0, 50).map(row => {
    const item = {}
    columns.forEach((col, i) => {
      const val = row[i]
      // Try to parse as number
      const num = parseFloat(val)
      item[col] = !isNaN(num) && col !== (chart.x || chart.nameKey) ? num : val
    })
    return item
  })
}

function renderChart(chart, data) {
  switch (chart.type) {
    case 'bar':
      return (
        <BarChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.1)" />
          <XAxis
            dataKey={chart.x}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            axisLine={{ stroke: 'rgba(148,163,184,0.2)' }}
            angle={data.length > 8 ? -35 : 0}
            textAnchor={data.length > 8 ? 'end' : 'middle'}
            height={data.length > 8 ? 80 : 30}
          />
          <YAxis
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            axisLine={{ stroke: 'rgba(148,163,184,0.2)' }}
          />
          <Tooltip contentStyle={tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: '0.8rem', color: '#94a3b8' }} />
          <Bar
            dataKey={chart.y}
            fill="url(#barGradient)"
            radius={[4, 4, 0, 0]}
            animationDuration={800}
          />
          <defs>
            <linearGradient id="barGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#14b8a6" stopOpacity={0.9} />
              <stop offset="100%" stopColor="#06b6d4" stopOpacity={0.6} />
            </linearGradient>
          </defs>
        </BarChart>
      )

    case 'line':
      return (
        <LineChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.1)" />
          <XAxis
            dataKey={chart.x}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            axisLine={{ stroke: 'rgba(148,163,184,0.2)' }}
          />
          <YAxis
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            axisLine={{ stroke: 'rgba(148,163,184,0.2)' }}
          />
          <Tooltip contentStyle={tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: '0.8rem', color: '#94a3b8' }} />
          <Line
            type="monotone"
            dataKey={chart.y}
            stroke="#14b8a6"
            strokeWidth={2.5}
            dot={{ fill: '#14b8a6', r: 3 }}
            activeDot={{ r: 6, fill: '#14b8a6', stroke: '#0a0e17', strokeWidth: 2 }}
            animationDuration={1000}
          />
        </LineChart>
      )

    case 'pie':
      return (
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            outerRadius={100}
            innerRadius={50}
            dataKey={chart.dataKey || chart.y}
            nameKey={chart.nameKey || chart.x}
            paddingAngle={2}
            animationDuration={800}
            label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
            labelLine={{ stroke: '#94a3b8' }}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip contentStyle={tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: '0.8rem', color: '#94a3b8' }} />
        </PieChart>
      )

    default:
      return (
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.1)" />
          <XAxis dataKey={chart.x} tick={{ fill: '#94a3b8', fontSize: 11 }} />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
          <Tooltip contentStyle={tooltipStyle} />
          <Bar dataKey={chart.y} fill="#14b8a6" radius={[4, 4, 0, 0]} />
        </BarChart>
      )
  }
}

export default ChartRenderer
