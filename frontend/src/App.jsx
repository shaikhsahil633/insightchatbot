import { useState, useRef, useEffect } from 'react'
import './index.css'
import ChatMessage from './components/ChatMessage'
import ChartRenderer from './components/ChartRenderer'
import Login from './components/Login'

const API_BASE = 'https://api.insight-ai.xbytedev.co'

const SUGGESTION_ICONS = ['📊', '🏪', '📈', '🏷️', '📦', '💰', '🔍', '🛒']

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [loadingStep, setLoadingStep] = useState(0)
  const [suggestions, setSuggestions] = useState([])
  const [healthStatus, setHealthStatus] = useState(null)
  const [sessionId] = useState(() => 'session_' + Date.now())
  const [isLoggedIn, setIsLoggedIn] = useState(() => {
    return localStorage.getItem('isLoggedIn') === 'true'
  })
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  // Fetch suggestions and health on mount
  useEffect(() => {
    fetchSuggestions()
    checkHealth()
    const healthInterval = setInterval(checkHealth, 30000)
    return () => clearInterval(healthInterval)
  }, [])

  async function fetchSuggestions() {
    try {
      const res = await fetch(`${API_BASE}/api/suggestions`)
      const data = await res.json()
      setSuggestions(data.suggestions || [])
    } catch {
      setSuggestions([
        "What are the top 10 most expensive products at Bilka?",
        "Compare average unit prices between Netto and Rema",
        "How many products are currently in stock?",
        "Which retailer has the most products on promotion?",
      ])
    }
  }

  async function checkHealth() {
    try {
      const res = await fetch(`${API_BASE}/api/health`)
      const data = await res.json()
      setHealthStatus(data)
    } catch {
      setHealthStatus({ status: 'offline', llm_provider: 'unknown', llm_status: 'unhealthy' })
    }
  }

  async function sendMessage(text) {
    const question = text || input.trim()
    if (!question || isLoading) return

    setInput('')
    setIsLoading(true)
    setLoadingStep(0)

    // Add user message
    const userMsg = { role: 'user', content: question, timestamp: new Date() }
    setMessages(prev => [...prev, userMsg])

    // Simulate loading steps
    const stepTimers = [
      setTimeout(() => setLoadingStep(1), 500),
      setTimeout(() => setLoadingStep(2), 1500),
    ]

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, session_id: sessionId }),
      })

      const data = await res.json()

      const botMsg = {
        role: 'bot',
        content: data.answer,
        sql: data.sql,
        data: data.data,
        chart: data.chart,
        error: data.error,
        latency: data.latency_ms,
        timestamp: new Date(),
      }

      setMessages(prev => [...prev, botMsg])
    } catch (err) {
      const errorMsg = {
        role: 'bot',
        content: `⚠️ Connection error: Could not reach the backend server. Please ensure the FastAPI server is running on port 8000.\n\nError: ${err.message}`,
        error: err.message,
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, errorMsg])
    } finally {
      stepTimers.forEach(clearTimeout)
      setIsLoading(false)
      setLoadingStep(0)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  function handleLogin() {
    setIsLoggedIn(true)
    localStorage.setItem('isLoggedIn', 'true')
  }

  function handleLogout() {
    setIsLoggedIn(false)
    localStorage.removeItem('isLoggedIn')
  }

  if (!isLoggedIn) {
    return <Login onLogin={handleLogin} />
  }

  const isOnline = healthStatus?.status === 'ok'

  return (
    <div className="app-container">
      {/* Premium Header */}
      <header className="app-header">
        <div className="header-brand">
          <div className="logo-container">
            <span className="logo-sparkle">✧</span>
          </div>
          <div className="header-titles">
            <h1 className="main-title">X-Byte AI</h1>
            <span className="sub-title">Enterprise Data Assistant</span>
          </div>
        </div>
        <div className="header-status">
          {healthStatus && (
            <div className="status-container">
              <span className="provider-badge">
                <span className="provider-icon">⚡</span>
                {healthStatus.llm_provider || 'ollama'}
              </span>
              <div className={`connection-status ${isOnline ? 'online' : 'offline'}`}>
                <div className="status-ping"></div>
                <span>{isOnline ? 'System Online' : 'System Offline'}</span>
              </div>
              <button className="logout-button" onClick={handleLogout} title="Sign Out">
                <span>Logout</span>
                <span>🚪</span>
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Main Chat Area */}
      <main className="main-content">
        <div className="messages-area">
          {messages.length === 0 && !isLoading ? (
            <WelcomeScreen
              suggestions={suggestions}
              onSuggestionClick={(q) => sendMessage(q)}
            />
          ) : (
            <div className="messages-list">
              {messages.map((msg, i) => (
                <ChatMessage key={i} message={msg} />
              ))}
              
              {isLoading && (
                <div className={`loading-indicator ${messages.length === 0 ? 'centered' : ''}`}>
                  <div className="loading-avatar">⚡</div>
                  <div className="loading-bubble">
                    <div className="loading-steps">
                      <div className={`loading-step ${loadingStep >= 0 ? 'active' : ''} ${loadingStep > 0 ? 'done' : ''}`}>
                        {loadingStep > 0 ? <span className="step-icon done">✓</span> : <span className="step-icon spinner"></span>}
                        Analyzing intent...
                      </div>
                      {loadingStep >= 1 && (
                        <div className={`loading-step ${loadingStep >= 1 ? 'active' : ''} ${loadingStep > 1 ? 'done' : ''}`}>
                          {loadingStep > 1 ? <span className="step-icon done">✓</span> : <span className="step-icon spinner"></span>}
                          Generating SQL query...
                        </div>
                      )}
                      {loadingStep >= 2 && (
                        <div className="loading-step active">
                          <span className="step-icon spinner"></span>
                          Executing query & summarizing...
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} className="messages-bottom-padding" />
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="input-area">
          <div className="input-wrapper">
            <textarea
              ref={inputRef}
              className="input-field"
              placeholder="Ask a question about your data..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              disabled={isLoading}
            />
            <button
              className="send-button"
              onClick={() => sendMessage()}
              disabled={!input.trim() || isLoading}
              title="Send message"
            >
              <svg className="send-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
              </svg>
            </button>
          </div>
          <div className="input-footer">
            X-Byte AI can make mistakes. Check important info.
          </div>
        </div>
      </main>
    </div>
  )
}

function WelcomeScreen({ suggestions, onSuggestionClick }) {
  return (
    <div className="welcome-screen">
      <div className="welcome-hero">
        <div className="welcome-icon-large">✧</div>
        <h2 className="welcome-title">Welcome to X-Byte AI</h2>
        <p className="welcome-desc">
          Your intelligent data assistant. Ask questions about grocery pricing, products, 
          retailers, and trends in plain English to get instant insights.
        </p>
      </div>
      <div className="suggestions-container">
        <h3 className="suggestions-title">Suggested Queries</h3>
        <div className="suggestions-grid">
          {suggestions.slice(0, 4).map((q, i) => (
            <button
              key={i}
              className="suggestion-card"
              onClick={() => onSuggestionClick(q)}
            >
              <div className="suggestion-icon-wrapper">
                {SUGGESTION_ICONS[i % SUGGESTION_ICONS.length]}
              </div>
              <span className="suggestion-text">{q}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

export default App
