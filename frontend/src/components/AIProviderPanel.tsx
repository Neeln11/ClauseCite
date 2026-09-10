/**
 * AIProviderPanel — paste your API key, everything else is automatic.
 *
 * The provider (OpenAI, Groq, OpenRouter…), base URL, and model are all
 * detected server-side from the key format. User sees only one input.
 */

import { useEffect, useRef, useState } from 'react'
import {
  clearProvider,
  configureProvider,
  getProviderOptions,
  getProviderStatus,
  type ProviderOption,
  type ProviderStatus,
} from '../api/client'

interface Props {
  onStatusChange?: (status: ProviderStatus) => void
}

/**
 * Live hint as the user types.
 *
 * Mirrors the prefix rules in backend/app/services/provider.py — the backend
 * remains the authority, this only avoids a round trip per keystroke. Order
 * matters: `sk-ant-` and `sk-or-` must be tested before the general `sk-`.
 */
function detectProviderFromKey(key: string): { name: string; icon: string } | null {
  const k = key.trim()
  if (!k) return null
  if (k.startsWith('sk-ant-')) return { name: 'Anthropic', icon: '✦' }
  if (k.startsWith('sk-or-')) return { name: 'OpenRouter', icon: '◈' }
  if (k.startsWith('gsk_')) return { name: 'Groq', icon: '▲' }
  if (k.startsWith('tog-')) return { name: 'Together AI', icon: '⊛' }
  if (k.startsWith('mis-')) return { name: 'Mistral AI', icon: '◎' }
  if (k.startsWith('AIza')) return { name: 'Google Gemini', icon: '✧' }
  if (k.startsWith('sk-')) return { name: 'OpenAI', icon: '⬡' }
  if (k.length >= 20) return { name: 'AI Provider', icon: '◌' }
  return null
}

export function AIProviderPanel({ onStatusChange }: Props) {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<ProviderStatus | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [keyVisible, setKeyVisible] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // 'auto' guesses the provider from the key's prefix, as before. Picking a
  // known id skips that guess; 'custom' targets any OpenAI-compatible
  // endpoint the backend has no detection rule for.
  const [providerOptions, setProviderOptions] = useState<ProviderOption[]>([])
  const [selectedProvider, setSelectedProvider] = useState('auto')
  const [customBaseUrl, setCustomBaseUrl] = useState('')
  const [customModel, setCustomModel] = useState('')

  const detected = detectProviderFromKey(apiKey)
  const isConnected = status?.mode === 'llm'
  const isCustom = selectedProvider === 'custom'

  useEffect(() => {
    // An unreachable backend is not this panel's problem to report — the chat
    // surface already says so. Swallowing it here keeps the failure to one
    // message instead of two, and stops an unhandled rejection.
    void getProviderStatus()
      .then((s) => {
        setStatus(s)
        onStatusChange?.(s)
      })
      .catch(() => setStatus(null))
    // A stale/empty list just means the dropdown offers only Auto-detect and
    // Custom — not worth surfacing as an error.
    void getProviderOptions()
      .then(setProviderOptions)
      .catch(() => setProviderOptions([]))
  }, [onStatusChange])

  // Auto-focus input when panel opens
  useEffect(() => {
    if (open && !isConnected) {
      setTimeout(() => inputRef.current?.focus(), 80)
    }
  }, [open, isConnected])

  const handleConnect = async () => {
    if (!apiKey.trim()) return
    if (isCustom && (!customBaseUrl.trim() || !customModel.trim())) return
    setError(null)
    setLoading(true)
    try {
      // 'auto' sends only the key, same as before — the backend detects
      // everything else from it. Any other choice overrides that guess.
      const result = await configureProvider({
        api_key: apiKey,
        ...(selectedProvider !== 'auto' ? { provider_id: selectedProvider } : {}),
        ...(isCustom ? { base_url: customBaseUrl.trim(), model: customModel.trim() } : {}),
      })
      setStatus(result)
      onStatusChange?.(result)
      setApiKey('')
      setSelectedProvider('auto')
      setCustomBaseUrl('')
      setCustomModel('')
      setOpen(false)
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : 'Connection failed. Check your API key and try again.'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const handleDisconnect = async () => {
    setLoading(true)
    try {
      const result = await clearProvider()
      setStatus(result)
      onStatusChange?.(result)
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') void handleConnect()
  }

  return (
    <div className="provider-panel">
      {/* Toggle header */}
      <button
        id="ai-provider-toggle"
        type="button"
        className={`provider-header ${isConnected ? 'provider-header--connected' : ''}`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="provider-header-left">
          <span className={`provider-dot ${isConnected ? 'provider-dot--on' : 'provider-dot--off'}`} />
          <span className="provider-header-label">
            {isConnected
              ? `${status?.provider_name ?? 'AI'} · ${status?.model}`
              : 'Connect AI (optional)'}
          </span>
        </span>
        <span className={`provider-chevron ${open ? 'provider-chevron--open' : ''}`}>▾</span>
      </button>

      {open && (
        <div className="provider-body">
          {isConnected ? (
            /* ── Connected state ── */
            <div className="provider-connected-state">
              <div className="provider-connected-badge">
                <span className="provider-connected-icon">✦</span>
                <div>
                  <div className="provider-connected-name">{status?.provider_name}</div>
                  <div className="provider-connected-model">{status?.model}</div>
                </div>
              </div>
              <p className="provider-status-msg">
                Answers now combine your documents with AI knowledge.
              </p>
              <button
                id="ai-provider-disconnect"
                type="button"
                className="provider-btn provider-btn--danger"
                disabled={loading}
                onClick={() => void handleDisconnect()}
              >
                {loading ? <span className="provider-spinner" /> : '↩'} Go offline
              </button>
            </div>
          ) : (
            /* ── Paste-and-go form ── */
            <div className="provider-form">
              <p className="provider-hint">
                Paste your API key — provider and model are detected automatically.
              </p>

              <div className="provider-field">
                <div className="provider-key-row">
                  <input
                    ref={inputRef}
                    id="provider-api-key"
                    type={keyVisible ? 'text' : 'password'}
                    className="provider-input provider-input--key"
                    placeholder="Paste API key…"
                    value={apiKey}
                    onChange={(e) => {
                      setApiKey(e.target.value)
                      setError(null)
                    }}
                    onKeyDown={handleKeyDown}
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <button
                    type="button"
                    className="provider-eye"
                    aria-label={keyVisible ? 'Hide key' : 'Show key'}
                    onClick={() => setKeyVisible((v) => !v)}
                    tabIndex={-1}
                  >
                    {keyVisible ? '🙈' : '👁'}
                  </button>
                </div>

                {/* Live detection hint — only meaningful while auto-detecting */}
                {selectedProvider === 'auto' &&
                  (detected ? (
                    <span className="provider-detected">
                      <span className="provider-detected-icon">{detected.icon}</span>
                      Detected: <strong>{detected.name}</strong>
                    </span>
                  ) : apiKey.trim().length > 0 ? (
                    <span className="provider-detected provider-detected--unknown">
                      ◌ Unrecognised key format — the provider will be identified
                      when you connect
                    </span>
                  ) : (
                    <span className="provider-key-note">
                      Supports OpenAI · Groq · OpenRouter · Mistral · Together AI
                    </span>
                  ))}
              </div>

              <div className="provider-field">
                <label className="provider-label" htmlFor="provider-select">
                  Provider isn't right, or using something else?
                </label>
                <select
                  id="provider-select"
                  className="provider-input provider-select"
                  value={selectedProvider}
                  onChange={(e) => {
                    setSelectedProvider(e.target.value)
                    setError(null)
                  }}
                >
                  <option value="auto">Auto-detect from key</option>
                  {providerOptions.map((p) => (
                    <option key={p.provider_id} value={p.provider_id}>
                      {p.provider_name}
                    </option>
                  ))}
                  <option value="custom">Custom / other (OpenAI-compatible)</option>
                </select>
              </div>

              {isCustom && (
                <div className="provider-field provider-custom-fields">
                  <input
                    id="provider-base-url"
                    className="provider-input"
                    placeholder="Base URL, e.g. https://your-server/v1"
                    value={customBaseUrl}
                    onChange={(e) => {
                      setCustomBaseUrl(e.target.value)
                      setError(null)
                    }}
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <input
                    id="provider-model"
                    className="provider-input"
                    placeholder="Model name, e.g. llama-3.1-70b"
                    value={customModel}
                    onChange={(e) => {
                      setCustomModel(e.target.value)
                      setError(null)
                    }}
                    autoComplete="off"
                    spellCheck={false}
                  />
                </div>
              )}

              {error && (
                <p className="provider-error" role="alert">
                  ⚠ {error}
                </p>
              )}

              <button
                id="ai-provider-connect"
                type="button"
                className="provider-btn provider-btn--primary"
                disabled={
                  !apiKey.trim() ||
                  loading ||
                  (isCustom && (!customBaseUrl.trim() || !customModel.trim()))
                }
                onClick={() => void handleConnect()}
              >
                {loading ? (
                  <>
                    <span className="provider-spinner" /> Connecting…
                  </>
                ) : (
                  'Connect'
                )}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
