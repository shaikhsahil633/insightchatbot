import { useState } from 'react'
import ChartRenderer from './ChartRenderer'

/**
 * Renders a single chat message (user or bot).
 * Bot messages can include SQL, data tables, and charts.
 */
function ChatMessage({ message }) {
  const [showSql, setShowSql] = useState(false)
  const isUser = message.role === 'user'

  return (
    <div className={`message ${message.role}`}>
      <div className="message-avatar">
        {isUser ? '👤' : '⚡'}
      </div>
      <div className="message-content">
        <div className="message-bubble">
          <MessageText text={message.content} />
        </div>

        {/* SQL Toggle */}
        {message.sql && (
          <>
            <button
              className="sql-toggle"
              onClick={() => setShowSql(!showSql)}
            >
              🔍 {showSql ? 'Hide' : 'Show'} SQL Query
            </button>
            {showSql && (
              <div className="sql-block">{message.sql}</div>
            )}
          </>
        )}

        {/* Chart */}
        {message.chart && message.data && (
          <ChartRenderer
            chart={message.chart}
            data={message.data}
          />
        )}

        {/* Data Table */}
        {message.data && message.data.columns && message.data.rows && message.data.rows.length > 0 && (
          <DataTable data={message.data} />
        )}

        {/* Meta info */}
        <div className="message-meta">
          {message.timestamp && (
            <span>{formatTime(message.timestamp)}</span>
          )}
          {message.latency > 0 && (
            <span>· {(message.latency / 1000).toFixed(1)}s</span>
          )}
          {message.data?.row_count !== undefined && (
            <span>· {message.data.row_count} rows</span>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * Renders markdown-like text with basic formatting.
 */
function MessageText({ text }) {
  if (!text) return null

  // Split into paragraphs
  const paragraphs = text.split('\n\n')

  return (
    <>
      {paragraphs.map((para, i) => {
        const lines = para.split('\n')
        return (
          <div key={i} style={{ marginBottom: i < paragraphs.length - 1 ? '12px' : 0 }}>
            {lines.map((line, j) => {
              // Handle bullet points
              if (line.match(/^[•\-\*]\s/)) {
                return <div key={j} style={{ paddingLeft: '16px', marginBottom: '4px' }}>{formatInline(line)}</div>
              }
              // Handle numbered lists
              if (line.match(/^\d+\.\s/)) {
                return <div key={j} style={{ paddingLeft: '16px', marginBottom: '4px' }}>{formatInline(line)}</div>
              }
              return <div key={j}>{formatInline(line)}</div>
            })}
          </div>
        )
      })}
    </>
  )
}

/**
 * Format inline markdown: **bold**, `code`
 */
function formatInline(text) {
  const parts = []
  let remaining = text
  let key = 0

  while (remaining.length > 0) {
    // Bold: **text**
    const boldMatch = remaining.match(/\*\*(.+?)\*\*/)
    // Code: `text`
    const codeMatch = remaining.match(/`(.+?)`/)

    if (boldMatch && (!codeMatch || boldMatch.index < codeMatch.index)) {
      if (boldMatch.index > 0) {
        parts.push(<span key={key++}>{remaining.slice(0, boldMatch.index)}</span>)
      }
      parts.push(<strong key={key++}>{boldMatch[1]}</strong>)
      remaining = remaining.slice(boldMatch.index + boldMatch[0].length)
    } else if (codeMatch) {
      if (codeMatch.index > 0) {
        parts.push(<span key={key++}>{remaining.slice(0, codeMatch.index)}</span>)
      }
      parts.push(
        <code key={key++} style={{
          background: 'rgba(20, 184, 166, 0.15)',
          padding: '1px 6px',
          borderRadius: '4px',
          fontSize: '0.85em',
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-accent)'
        }}>
          {codeMatch[1]}
        </code>
      )
      remaining = remaining.slice(codeMatch.index + codeMatch[0].length)
    } else {
      parts.push(<span key={key++}>{remaining}</span>)
      break
    }
  }

  return parts.length > 0 ? parts : text
}

/**
 * Renders a sortable data table from query results.
 */
function DataTable({ data }) {
  const [sortCol, setSortCol] = useState(null)
  const [sortAsc, setSortAsc] = useState(true)
  const maxDisplay = 20

  const handleSort = (colIdx) => {
    if (sortCol === colIdx) {
      setSortAsc(!sortAsc)
    } else {
      setSortCol(colIdx)
      setSortAsc(true)
    }
  }

  let displayRows = [...data.rows]
  if (sortCol !== null) {
    displayRows.sort((a, b) => {
      const valA = a[sortCol] || ''
      const valB = b[sortCol] || ''
      // Try numeric sort
      const numA = parseFloat(valA)
      const numB = parseFloat(valB)
      if (!isNaN(numA) && !isNaN(numB)) {
        return sortAsc ? numA - numB : numB - numA
      }
      return sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA)
    })
  }

  const truncated = displayRows.length > maxDisplay
  const visibleRows = displayRows.slice(0, maxDisplay)

  return (
    <>
      <div className="data-table-container">
        <table className="data-table">
          <thead>
            <tr>
              {data.columns.map((col, i) => (
                <th
                  key={i}
                  onClick={() => handleSort(i)}
                  style={{ cursor: 'pointer', userSelect: 'none' }}
                >
                  {col}
                  {sortCol === i && (sortAsc ? ' ↑' : ' ↓')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j} title={cell || ''}>{cell || '—'}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row-count-badge">
        📊 Showing {visibleRows.length} of {data.row_count} rows
        {truncated && ' (scroll for more)'}
      </div>
    </>
  )
}

function formatTime(date) {
  const d = new Date(date)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export default ChatMessage
