import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API_BASE = window.desktopAppConfig?.apiBase || import.meta.env.VITE_API_BASE || 'http://localhost:8080/api';
const TOOL_PROVIDERS = ['google_tts', 'pexels', 'pixabay', 'freesound'];
const DEFAULT_LLM_OPTIONS = [
  { provider: 'openai', label: 'OpenAI / ChatGPT', models: ['gpt-4o-mini', 'gpt-4o', 'gpt-4.1-mini', 'gpt-4.1'], default_model: 'gpt-4o-mini' },
  { provider: 'anthropic', label: 'Claude', models: ['claude-3-5-haiku-20241022', 'claude-3-5-sonnet-20241022', 'claude-3-7-sonnet-20250219', 'claude-sonnet-4-20250514'], default_model: 'claude-3-5-haiku-20241022' },
  { provider: 'gemini', label: 'Gemini', models: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-1.5-flash', 'gemini-1.5-pro'], default_model: 'gemini-2.5-flash' },
  { provider: 'groq', label: 'Groq', models: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'llama3-70b-8192', 'mixtral-8x7b-32768'], default_model: 'llama-3.3-70b-versatile' },
];
const TERMINAL_STATUSES = new Set(['succeeded', 'failed']);
const ISSUE_TYPES = [
  ['script', 'Script / narration'],
  ['voice', 'Voice / audio'],
  ['visuals', "Visuals don't match"],
  ['captions', 'Captions'],
  ['music', 'Music'],
  ['pacing', 'Pacing'],
];
const TOOL_REQUIREMENT_TEXT = 'Required: one validated LLM provider. Google TTS, Pexels, and Pixabay are optional upgrades; EdgeTTS and free image fallbacks keep the desktop pipeline runnable.';
const PROMPT_SUGGESTIONS = [
  'Generate one final 30 second scary short in the selected style.',
  'Make the voice faster and keep the same topic.',
  'Use more stock video and stronger visual variety.',
  'Shorten it to 20 seconds with punchier captions.',
];
const SETTING_ORDER = ['duration', 'voice_speed', 'image_count', 'caption_words', 'music_volume', 'schedule'];
const SETTING_LABELS = {
  duration: 'Duration',
  voice_speed: 'Voice speed',
  image_count: 'Visual cues',
  caption_words: 'Caption density',
  music_volume: 'Music volume',
  schedule: 'Schedule',
};
const PROVIDER_LABELS = {
  google_tts: 'Google TTS',
  pexels: 'Pexels stock video',
  pixabay: 'Pixabay image fallback',
  freesound: 'Freesound music + SFX',
  master_agent: 'Master',
  topic_discovery_agent: 'Discovery',
  research_agent: 'Research',
  script_agent: 'Script',
  validation_agent: 'Validation',
  asset_agent: 'Assets',
  audio_agent: 'Voice',
  caption_agent: 'Captions',
  render_agent: 'Render',
  thumbnail_agent: 'Thumbnail',
};

function apiClient(token) {
  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers || {}),
      },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${response.status}`);
    }
    return response.json();
  }

  async function blob(path) {
    const response = await fetch(toAbsoluteAppUrl(path), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed: ${response.status}`);
    }
    return response.blob();
  }

  return {
    signup: (payload) => request('/auth/signup', { method: 'POST', body: JSON.stringify(payload) }),
    login: (payload) => request('/auth/login', { method: 'POST', body: JSON.stringify(payload) }),
    me: () => request('/auth/me'),
    onboarding: () => request('/onboarding'),
    resetChat: () => request('/onboarding/reset', { method: 'POST' }),
    chats: () => request('/chats'),
    createChat: (payload) => request('/chats', { method: 'POST', body: JSON.stringify(payload) }),
    activateChat: (chatId) => request(`/chats/${chatId}/activate`, { method: 'POST' }),
    messages: (chatId) => request(`/chats/${chatId}/messages`),
    sendMessage: (chatId, payload) => request(`/chats/${chatId}/messages`, { method: 'POST', body: JSON.stringify(payload) }),
    apiKeys: () => request('/onboarding/api-keys'),
    saveApiKey: (payload) => request('/onboarding/api-keys', { method: 'POST', body: JSON.stringify(payload) }),
    genres: () => request('/onboarding/genres'),
    saveIntent: (payload) => request('/onboarding/genre-intent', { method: 'POST', body: JSON.stringify(payload) }),
    startCalibration: (payload) => request('/onboarding/calibration/start', { method: 'POST', body: JSON.stringify(payload) }),
    completeCalibration: (payload) => request('/onboarding/calibration/complete', { method: 'POST', body: JSON.stringify(payload) }),
    generate: (payload) => request('/generate', { method: 'POST', body: JSON.stringify(payload) }),
    saveFeedback: (jobId, payload) => request(`/generate/jobs/${jobId}/feedback`, { method: 'POST', body: JSON.stringify(payload) }),
    importKnowledge: (file, { reset = true, backup = true } = {}) => {
      const data = new FormData();
      data.append('file', file);
      return request(`/knowledge/import.xlsx?reset=${reset ? 'true' : 'false'}&backup=${backup ? 'true' : 'false'}`, {
        method: 'POST',
        body: data,
      });
    },
    jobs: () => request('/jobs'),
    job: (jobId) => request(`/jobs/${jobId}`),
    jobProgress: (jobId) => request(`/jobs/${jobId}/progress`),
    jobLogs: (jobId) => request(`/jobs/${jobId}/logs`),
    blob,
  };
}

function toAbsoluteAppUrl(url) {
  if (!url) return '';
  if (/^https?:\/\//i.test(url)) return url;
  const apiUrl = new URL(API_BASE);
  return `${apiUrl.origin}${url.startsWith('/') ? url : `/${url}`}`;
}

function defaultSettings() {
  return {
    duration: 30,
    voice_speed: 1,
    caption_words: 4,
    image_count: 8,
    music_volume: 0.18,
    schedule: 'now',
  };
}

function SelectField({ label: fieldLabel, value, options, onChange, placeholder = 'Select option', className = '' }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef(null);
  const normalizedOptions = options.map((option) => (
    typeof option === 'string' ? { value: option, label: option } : option
  ));
  const selected = normalizedOptions.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return undefined;
    function onDocumentClick(event) {
      if (ref.current && !ref.current.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onDocumentClick);
    return () => document.removeEventListener('mousedown', onDocumentClick);
  }, [open]);

  function choose(nextValue) {
    onChange(nextValue);
    setOpen(false);
  }

  return (
    <label className={`ui-field ${className}`} htmlFor={id} ref={ref}>
      <span>{fieldLabel}</span>
      <button
        id={id}
        type="button"
        className={`ui-select-trigger ${open ? 'open' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setOpen(false);
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            setOpen(!open);
          }
        }}
      >
        <span>{selected?.label || placeholder}</span>
        <ChevronDownIcon />
      </button>
      {open && (
        <div className="ui-select-content" role="listbox">
          {normalizedOptions.map((option) => (
            <button
              type="button"
              role="option"
              aria-selected={option.value === value}
              className={option.value === value ? 'ui-select-item selected' : 'ui-select-item'}
              key={option.value}
              onClick={() => choose(option.value)}
            >
              {option.label}
            </button>
          ))}
          {!normalizedOptions.length && <span className="ui-select-empty">No options available</span>}
        </div>
      )}
    </label>
  );
}

function App() {
  const [token, setToken] = useState(localStorage.getItem('desktopapp_token') || '');
  const [user, setUser] = useState(null);
  const [state, setState] = useState(null);
  const [error, setError] = useState('');
  const [page, setPage] = useState('studio');
  const [activeChatId, setActiveChatId] = useState(localStorage.getItem('desktopapp_active_chat') || '');
  const client = useMemo(() => apiClient(token), [token]);

  async function refreshState() {
    if (!token) return;
    const [me, onboarding] = await Promise.all([client.me(), client.onboarding()]);
    setUser(me);
    setState(onboarding);
    if (onboarding.active_chat_id && onboarding.active_chat_id !== activeChatId) {
      localStorage.setItem('desktopapp_active_chat', onboarding.active_chat_id);
      setActiveChatId(onboarding.active_chat_id);
    }
  }

  useEffect(() => {
    refreshState().catch(() => {
      localStorage.removeItem('desktopapp_token');
      setToken('');
      setUser(null);
      setState(null);
    });
  }, [token]);

  function onAuth(nextToken) {
    localStorage.setItem('desktopapp_token', nextToken);
    setToken(nextToken);
  }

  async function onSelectChat(chatId) {
    localStorage.setItem('desktopapp_active_chat', chatId);
    setActiveChatId(chatId);
    setPage('studio');
    try {
      await client.activateChat(chatId);
      await refreshState();
    } catch (err) {
      console.error(err);
    }
  }

  async function startNewChat() {
    const reset = await client.resetChat();
    if (reset.chat?.id) {
      await onSelectChat(reset.chat.id);
    }
    await refreshState();
    return reset.chat;
  }

  if (!token) {
    return <AuthScreen onAuth={onAuth} error={error} setError={setError} />;
  }
  if (!state) {
    return <Shell user={user}><p className="muted">Loading workspace...</p></Shell>;
  }
  if (page === 'settings' || !state.api_setup_complete) {
    return (
      <SettingsPage
        client={client}
        user={user}
        state={state}
        onDone={async () => {
          await refreshState();
          setPage('studio');
        }}
        onNavigate={setPage}
        activeChatId={activeChatId}
        onSelectChat={onSelectChat}
        onNewChat={startNewChat}
        onLogout={() => logout(setToken)}
        onReset={refreshState}
      />
    );
  }
  if (!state.genre_id || !state.user_intent) {
    return <IntentScreen client={client} user={user} onDone={refreshState} onLogout={() => logout(setToken)} onReset={refreshState} onNavigate={setPage} page={page} activeChatId={activeChatId} onSelectChat={onSelectChat} onNewChat={startNewChat} />;
  }
  if (state.calibration_status !== 'completed') {
    return <CalibrationScreen client={client} user={user} state={state} onDone={refreshState} onLogout={() => logout(setToken)} onReset={refreshState} onNavigate={setPage} page={page} activeChatId={activeChatId} onSelectChat={onSelectChat} onNewChat={startNewChat} />;
  }
  return <Dashboard client={client} user={user} state={state} onLogout={() => logout(setToken)} onReset={refreshState} onNavigate={setPage} page={page} activeChatId={activeChatId} onSelectChat={onSelectChat} onNewChat={startNewChat} />;
}

function logout(setToken) {
  localStorage.removeItem('desktopapp_token');
  setToken('');
}

function AuthScreen({ onAuth, error, setError }) {
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [loading, setLoading] = useState(false);
  const client = apiClient('');

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      const payload = mode === 'signup'
        ? await client.signup({ email, password, display_name: displayName })
        : await client.login({ email, password });
      onAuth(payload.access_token);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-page">
      <section className="hero-card">
        <p className="eyebrow">YouTube Shorts Automation</p>
        <h1>Build shorts with a calibrated video agent.</h1>
        <p className="muted">Sign in, connect your API keys, pick a genre style, and let the pipeline generate preview-ready videos.</p>
      </section>
      <form onSubmit={submit} className="auth-card">
        <h2>{mode === 'signup' ? 'Create account' : 'Welcome back'}</h2>
        {mode === 'signup' && <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Display name" />}
        <input value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Email" type="email" required />
        <input value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Password" type="password" minLength={8} maxLength={256} required />
        {error && <p className="error">{error}</p>}
        <button disabled={loading}>{loading ? 'Working...' : mode === 'signup' ? 'Sign up' : 'Log in'}</button>
        <button type="button" className="ghost" onClick={() => setMode(mode === 'signup' ? 'login' : 'signup')}>
          {mode === 'signup' ? 'Already have an account?' : 'Need an account?'}
        </button>
      </form>
    </main>
  );
}

function Shell({ user, children, onLogout, client, onReset, page = 'studio', onNavigate, activeChatId, onSelectChat, onNewChat }) {
  const [creating, setCreating] = useState(false);
  const [resetError, setResetError] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(true);

  async function newChat() {
    if (!client || creating) return;
    setCreating(true);
    setResetError('');
    try {
      await onNewChat?.();
      await onReset?.();
    } catch (err) {
      setResetError(err.message);
    } finally {
      setCreating(false);
    }
  }

  return (
    <main className={`app-frame ${client && sidebarOpen ? 'sidebar-open' : 'sidebar-closed'}`}>
      {client && (
        <ChatSidebar
          client={client}
          open={sidebarOpen}
          activeChatId={activeChatId}
          onSelectChat={onSelectChat}
          onNewChat={newChat}
          creating={creating}
        />
      )}
      {client && (
        <button className="sidebar-edge-toggle" title={sidebarOpen ? 'Close history' : 'Open history'} aria-label={sidebarOpen ? 'Close history' : 'Open history'} onClick={() => setSidebarOpen(!sidebarOpen)}>
          <SidebarIcon open={sidebarOpen} />
        </button>
      )}
      <section className="app-shell">
        <header className="topbar">
          <div className="brand-row">
            <div>
              <p className="eyebrow">Modular Shorts Studio</p>
              <h1>Creator Pipeline</h1>
            </div>
          </div>
          <div className="user-pill">
            <span>{user?.email || 'signed in'}</span>
            {client && onNavigate && (
              <div className="desktop-nav" aria-label="Main navigation">
                <button className={page === 'studio' ? 'nav-button active' : 'nav-button'} onClick={() => onNavigate('studio')}>
                  Studio
                </button>
                <button className={page === 'settings' ? 'nav-button active' : 'nav-button'} onClick={() => onNavigate('settings')}>
                  <SettingsIcon />
                  Settings
                </button>
              </div>
            )}
            {client && onNewChat && (
              <button className="icon-button" title="New chat" aria-label="New chat" disabled={creating} onClick={newChat}>
                <NewChatIcon spinning={creating} />
              </button>
            )}
            {onLogout && <button className="ghost small" onClick={onLogout}>Log out</button>}
          </div>
        </header>
        <div className="app-content">
          {resetError && <p className="error top-error">{resetError}</p>}
          {children}
        </div>
      </section>
    </main>
  );
}

function ApiSetupScreen({ client, user, onDone, onLogout, onReset }) {
  const [setup, setSetup] = useState(null);
  const [values, setValues] = useState({});
  const [llmProvider, setLlmProvider] = useState('openai');
  const [llmModel, setLlmModel] = useState('gpt-4o-mini');
  const [llmKey, setLlmKey] = useState('');
  const [saving, setSaving] = useState('');
  const [error, setError] = useState('');

  async function refresh() {
    const nextSetup = await client.apiKeys();
    setSetup(nextSetup);
    syncSelectedLlm(nextSetup);
  }

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, []);

  function syncSelectedLlm(nextSetup) {
    if (!nextSetup) return;
    const options = getLlmOptions(nextSetup);
    const providers = options.map((item) => item.provider);
    const selectedStatus = nextSetup.keys.find((item) => providers.includes(item.provider) && item.configured && item.status === 'passed')
      || nextSetup.keys.find((item) => providers.includes(item.provider) && item.configured);
    const selectedProvider = selectedStatus?.provider || llmProvider || options[0]?.provider || 'openai';
    const option = options.find((item) => item.provider === selectedProvider) || options[0];
    setLlmProvider(selectedProvider);
    setLlmModel(selectedStatus?.model || option?.default_model || option?.models?.[0] || '');
  }

  async function save(provider, model = '', valueOverride = null) {
    setSaving(provider);
    setError('');
    try {
      const nextSetup = await client.saveApiKey({ provider, value: valueOverride ?? values[provider] ?? '', model });
      setSetup(nextSetup);
      const status = nextSetup.keys.find((item) => item.provider === provider);
      if (status && status.status !== 'passed') {
        setError(`${label(provider)} validation failed: ${status.status}`);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving('');
    }
  }

  async function saveSelectedLlm() {
    setValues({ ...values, [llmProvider]: llmKey });
    await save(llmProvider, llmModel, llmKey);
  }

  function onProviderChange(provider) {
    const option = getLlmOptions(setup).find((item) => item.provider === provider);
    const status = setup?.keys.find((item) => item.provider === provider);
    setLlmProvider(provider);
    setLlmModel(status?.model || option?.default_model || option?.models?.[0] || '');
    setLlmKey('');
    setError('');
  }

  const llmOptions = getLlmOptions(setup);
  const selectedLlmOption = llmOptions.find((item) => item.provider === llmProvider) || llmOptions[0];
  const selectedLlmStatus = setup?.keys.find((item) => item.provider === llmProvider);

  return (
    <Shell user={user} onLogout={onLogout} client={client} onReset={onReset}>
      <section className="panel narrow">
        <StepHeader step="Step 1" title="Choose Model + Connect APIs" text="Pick the LLM provider and model version, paste the API key, then press Enter or Save + Test." />
        {error && <p className="error">{error}</p>}
        <div className="llm-card">
          <div>
            <p className="eyebrow">LLM provider</p>
            <h3>{selectedLlmOption?.label || 'OpenAI / ChatGPT'}</h3>
            <p className="muted">This selected provider/model is saved and passed into the pipeline for script and creative decisions.</p>
          </div>
          <div className="llm-grid">
            <SelectField
              label="Provider"
              value={llmProvider}
              onChange={onProviderChange}
              options={llmOptions.map((option) => ({ value: option.provider, label: option.label }))}
            />
            <SelectField
              label="Model version"
              value={llmModel}
              onChange={setLlmModel}
              options={(selectedLlmOption?.models || []).map((model) => ({ value: model, label: model }))}
            />
            <label className="llm-key-field">API key
              <input
                value={llmKey}
                onChange={(event) => setLlmKey(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && llmKey.trim()) saveSelectedLlm();
                }}
                placeholder={selectedLlmStatus?.configured ? `Saved ${selectedLlmStatus.source} key. Paste a new key to replace.` : `Paste ${selectedLlmOption?.label || 'LLM'} API key`}
                type="password"
              />
            </label>
            <button disabled={saving === llmProvider || !llmKey.trim()} onClick={saveSelectedLlm}>
              {saving === llmProvider ? 'Validating...' : 'Save + Test LLM'}
            </button>
          </div>
          <div className="status-strip">
            <span className={`dot ${selectedLlmStatus?.status === 'passed' ? 'ok' : ''}`} />
            <strong>{selectedLlmStatus?.status === 'passed' ? 'LLM ready' : 'LLM not ready'}</strong>
            <small>{selectedLlmStatus?.configured ? `${selectedLlmStatus.source} · ${selectedLlmStatus.model || llmModel}` : 'No key saved yet'}</small>
            {selectedLlmStatus?.status && selectedLlmStatus.status !== 'passed' && <small className="error">{selectedLlmStatus.status}</small>}
          </div>
        </div>
        <div className="key-grid">
          {TOOL_PROVIDERS.map((provider) => {
            const status = setup?.keys.find((item) => item.provider === provider);
            return (
              <article className="key-row" key={provider}>
                <div>
                  <strong>{label(provider)}</strong>
                  <small>{status?.source === 'env' ? 'Configured from .env' : status?.status || 'missing'}</small>
                </div>
                <input
                  value={values[provider] || ''}
                  onChange={(event) => setValues({ ...values, [provider]: event.target.value })}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && (values[provider] || '').trim()) save(provider);
                  }}
                  placeholder={status?.configured ? 'Replace saved value' : 'Paste key or path'}
                  type={provider === 'google_tts' ? 'text' : 'password'}
                />
                <button disabled={saving === provider} onClick={() => save(provider)}>{saving === provider ? 'Testing...' : 'Save + Test'}</button>
                <span className={`dot ${status?.status === 'passed' ? 'ok' : ''}`} />
              </article>
            );
          })}
        </div>
        <div className="action-row">
          <p className="muted">{TOOL_REQUIREMENT_TEXT}</p>
          <button disabled={!setup?.complete} onClick={onDone}>Continue</button>
        </div>
      </section>
    </Shell>
  );
}

function getLlmOptions(setup) {
  return setup?.llm_options?.length ? setup.llm_options : DEFAULT_LLM_OPTIONS;
}

function ChatSidebar({ client, open, activeChatId, onSelectChat, onNewChat, creating }) {
  const [chats, setChats] = useState([]);
  const [error, setError] = useState('');

  async function refresh() {
    const items = await client.chats();
    setChats(items);
    if (!activeChatId && items[0]?.id) {
      onSelectChat?.(items[0].id);
    }
  }

  useEffect(() => {
    if (!open) return undefined;
    refresh().catch((err) => setError(err.message));
    const timer = setInterval(() => refresh().catch(console.error), 7000);
    return () => clearInterval(timer);
  }, [open, activeChatId]);

  if (!open) return null;

  return (
    <aside className="chat-sidebar">
      <div className="sidebar-head">
        <div>
          <p className="eyebrow">History</p>
          <h2>Chats</h2>
        </div>
        <button className="icon-button" title="New chat" aria-label="New chat" disabled={creating} onClick={async () => {
          await onNewChat?.();
          await refresh();
        }}>
          <NewChatIcon spinning={creating} />
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="chat-list">
        {chats.map((chat) => (
          <button
            key={chat.id}
            className={chat.id === activeChatId ? 'chat-history-item active' : 'chat-history-item'}
            onClick={() => onSelectChat?.(chat.id)}
          >
            <strong>{chat.title || 'New chat'}</strong>
            <small>{formatDate(chat.updated_at)}</small>
          </button>
        ))}
        {chats.length === 0 && <p className="muted">No chats yet. Start a new one.</p>}
      </div>
    </aside>
  );
}

function SettingsPage({ client, user, state, onDone, onNavigate, onLogout, onReset, activeChatId, onSelectChat, onNewChat }) {
  return (
    <Shell user={user} onLogout={onLogout} client={client} onReset={onReset} page="settings" onNavigate={onNavigate} activeChatId={activeChatId} onSelectChat={onSelectChat} onNewChat={onNewChat}>
      <section className="settings-page">
        <div className="settings-hero panel">
          <p className="eyebrow">{state?.api_setup_complete ? 'Settings' : 'Initial setup'}</p>
          <h2>API Keys + Model</h2>
          <p className="muted">Change the LLM provider, model version, and online tool keys used by future jobs. This page is also used during initialization so setup and later edits stay identical.</p>
        </div>
        <ApiKeySettingsPanel
          client={client}
          continueLabel={state?.api_setup_complete ? 'Save settings' : 'Continue to studio'}
          onDone={async () => {
            await onDone?.();
          }}
        />
        <KnowledgeImportExportPanel client={client} />
      </section>
    </Shell>
  );
}

function KnowledgeImportExportPanel({ client }) {
  const [file, setFile] = useState(null);
  const [reset, setReset] = useState(true);
  const [backup, setBackup] = useState(true);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  async function downloadKnowledge(path, filename) {
    setBusy(path);
    setError('');
    setMessage('');
    try {
      const artifact = await client.blob(path);
      const url = URL.createObjectURL(artifact);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  }

  async function importSelected() {
    if (!file || busy) return;
    setBusy('import');
    setError('');
    setMessage('');
    try {
      const result = await client.importKnowledge(file, { reset, backup });
      const counts = Object.entries(result.counts || {})
        .map(([key, value]) => `${key}: ${value}`)
        .join(' · ');
      setMessage(`Imported ${file.name}. ${counts}`);
      setFile(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  }

  return (
    <div className="knowledge-panel panel">
      <div>
        <p className="eyebrow">Knowledge database</p>
        <h3>Import / Export Genre Data</h3>
        <p className="muted">Use Excel workbooks to seed grounded topics, genre rules, hooks, visual rules, and research sources.</p>
      </div>
      <div className="knowledge-actions">
        <button
          className="ghost"
          disabled={Boolean(busy)}
          onClick={() => downloadKnowledge('/api/knowledge/real-world-seed.xlsx', 'Genre_Knowledge_Real_World_Seed.xlsx')}
        >
          {busy === '/api/knowledge/real-world-seed.xlsx' ? 'Preparing...' : 'Download seed'}
        </button>
        <button
          className="ghost"
          disabled={Boolean(busy)}
          onClick={() => downloadKnowledge('/api/knowledge/export.xlsx', 'Genre_Knowledge_DB_Export.xlsx')}
        >
          {busy === '/api/knowledge/export.xlsx' ? 'Exporting...' : 'Export DB'}
        </button>
      </div>
      <div className="knowledge-import-row">
        <label className="file-picker">
          <span>{file?.name || 'Choose .xlsx workbook'}</span>
          <input type="file" accept=".xlsx" onChange={(event) => setFile(event.target.files?.[0] || null)} />
        </label>
        <label className="check-row">
          <input type="checkbox" checked={reset} onChange={(event) => setReset(event.target.checked)} />
          <span>Reset knowledge tables</span>
        </label>
        <label className="check-row">
          <input type="checkbox" checked={backup} onChange={(event) => setBackup(event.target.checked)} />
          <span>Backup first</span>
        </label>
        <button disabled={!file || Boolean(busy)} onClick={importSelected}>
          {busy === 'import' ? 'Importing...' : 'Import workbook'}
        </button>
      </div>
      {message && <p className="success">{message}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function ApiKeySettingsPanel({ client, onDone, continueLabel = 'Continue' }) {
  const [setup, setSetup] = useState(null);
  const [values, setValues] = useState({});
  const [llmProvider, setLlmProvider] = useState('openai');
  const [llmModel, setLlmModel] = useState('gpt-4o-mini');
  const [llmKey, setLlmKey] = useState('');
  const [saving, setSaving] = useState('');
  const [error, setError] = useState('');

  async function refresh() {
    const nextSetup = await client.apiKeys();
    setSetup(nextSetup);
    syncSelectedLlm(nextSetup);
  }

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, []);

  function syncSelectedLlm(nextSetup) {
    if (!nextSetup) return;
    const options = getLlmOptions(nextSetup);
    const providers = options.map((item) => item.provider);
    const selectedStatus = nextSetup.keys.find((item) => providers.includes(item.provider) && item.configured && item.status === 'passed')
      || nextSetup.keys.find((item) => providers.includes(item.provider) && item.configured);
    const selectedProvider = selectedStatus?.provider || llmProvider || options[0]?.provider || 'openai';
    const option = options.find((item) => item.provider === selectedProvider) || options[0];
    setLlmProvider(selectedProvider);
    setLlmModel(selectedStatus?.model || option?.default_model || option?.models?.[0] || '');
  }

  async function save(provider, model = '', valueOverride = null) {
    setSaving(provider);
    setError('');
    try {
      const nextSetup = await client.saveApiKey({ provider, value: valueOverride ?? values[provider] ?? '', model });
      setSetup(nextSetup);
      const status = nextSetup.keys.find((item) => item.provider === provider);
      if (status && status.status !== 'passed') {
        setError(`${label(provider)} validation failed: ${status.status}`);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving('');
    }
  }

  async function saveSelectedLlm() {
    setValues({ ...values, [llmProvider]: llmKey });
    await save(llmProvider, llmModel, llmKey);
  }

  function onProviderChange(provider) {
    const option = getLlmOptions(setup).find((item) => item.provider === provider);
    const status = setup?.keys.find((item) => item.provider === provider);
    setLlmProvider(provider);
    setLlmModel(status?.model || option?.default_model || option?.models?.[0] || '');
    setLlmKey('');
    setError('');
  }

  const llmOptions = getLlmOptions(setup);
  const selectedLlmOption = llmOptions.find((item) => item.provider === llmProvider) || llmOptions[0];
  const selectedLlmStatus = setup?.keys.find((item) => item.provider === llmProvider);

  return (
    <div className="api-settings-panel">
      {error && <p className="error">{error}</p>}
      <div className="llm-card">
        <div>
          <p className="eyebrow">LLM provider</p>
          <h3>{selectedLlmOption?.label || 'OpenAI / ChatGPT'}</h3>
          <p className="muted">This selected provider/model is saved and passed into the pipeline for script and creative decisions.</p>
        </div>
        <div className="llm-grid">
          <SelectField
            label="Provider"
            value={llmProvider}
            onChange={onProviderChange}
            options={llmOptions.map((option) => ({ value: option.provider, label: option.label }))}
          />
          <SelectField
            label="Model version"
            value={llmModel}
            onChange={setLlmModel}
            options={(selectedLlmOption?.models || []).map((model) => ({ value: model, label: model }))}
          />
          <label className="llm-key-field">API key
            <input
              value={llmKey}
              onChange={(event) => setLlmKey(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && llmKey.trim()) saveSelectedLlm();
              }}
              placeholder={selectedLlmStatus?.configured ? `Saved ${selectedLlmStatus.source} key. Paste a new key to replace.` : `Paste ${selectedLlmOption?.label || 'LLM'} API key`}
              type="password"
            />
          </label>
          <button disabled={saving === llmProvider || !llmKey.trim()} onClick={saveSelectedLlm}>
            {saving === llmProvider ? 'Validating...' : 'Save + Test LLM'}
          </button>
        </div>
        <div className="status-strip">
          <span className={`dot ${selectedLlmStatus?.status === 'passed' ? 'ok' : ''}`} />
          <strong>{selectedLlmStatus?.status === 'passed' ? 'LLM ready' : 'LLM not ready'}</strong>
          <small>{selectedLlmStatus?.configured ? `${selectedLlmStatus.source} · ${selectedLlmStatus.model || llmModel}` : 'No key saved yet'}</small>
          {selectedLlmStatus?.status && selectedLlmStatus.status !== 'passed' && <small className="error">{selectedLlmStatus.status}</small>}
        </div>
      </div>
      <div className="key-grid">
        {TOOL_PROVIDERS.map((provider) => {
          const status = setup?.keys.find((item) => item.provider === provider);
          return (
            <article className="key-row" key={provider}>
              <div>
                <strong>{label(provider)}</strong>
                <small>{status?.source === 'env' ? 'Configured from .env' : status?.status || 'missing'}</small>
              </div>
              <input
                value={values[provider] || ''}
                onChange={(event) => setValues({ ...values, [provider]: event.target.value })}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && (values[provider] || '').trim()) save(provider);
                }}
                placeholder={status?.configured ? 'Replace saved value' : 'Paste key or path'}
                type={provider === 'google_tts' ? 'text' : 'password'}
              />
              <button disabled={saving === provider} onClick={() => save(provider)}>{saving === provider ? 'Testing...' : 'Save + Test'}</button>
              <span className={`dot ${status?.status === 'passed' ? 'ok' : ''}`} />
            </article>
          );
        })}
      </div>
      <div className="action-row">
        <p className="muted">{TOOL_REQUIREMENT_TEXT}</p>
        <button disabled={!setup?.complete} onClick={onDone}>{continueLabel}</button>
      </div>
    </div>
  );
}

function IntentScreen({ client, user, onDone, onLogout, onReset, onNavigate, page = 'studio', activeChatId, onSelectChat, onNewChat }) {
  const [genres, setGenres] = useState([]);
  const [genreId, setGenreId] = useState('scary_stories');
  const [intent, setIntent] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    client.genres().then((items) => {
      setGenres(items);
      if (items[0]) setGenreId(items[0].genre_id);
    }).catch((err) => setError(err.message));
  }, []);

  async function submit() {
    setError('');
    try {
      await client.saveIntent({ genre_id: genreId, user_intent: intent });
      await onDone();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <Shell user={user} onLogout={onLogout} client={client} onReset={onReset} page={page} onNavigate={onNavigate} activeChatId={activeChatId} onSelectChat={onSelectChat} onNewChat={onNewChat}>
      <section className="panel narrow">
        <StepHeader step="Step 2" title="Pick Genre + Intent" text="Tell the agent what good looks like before it makes calibration samples." />
        <SelectField
          label="Genre"
          value={genreId}
          onChange={setGenreId}
          options={genres.map((genre) => ({ value: genre.genre_id, label: genre.display_name }))}
        />
        <textarea
          value={intent}
          onChange={(event) => setIntent(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && intent.trim()) {
              event.preventDefault();
              submit();
            }
          }}
          placeholder="Example: dark, creepy stories with slow building dread, simple English, more frames, and a twist that feels earned."
        />
        {error && <p className="error">{error}</p>}
        <button disabled={!intent.trim()} onClick={submit}>Save intent and start samples</button>
      </section>
    </Shell>
  );
}

function CalibrationScreen({ client, user, state, onDone, onLogout, onReset, onNavigate, page = 'studio', activeChatId, onSelectChat, onNewChat }) {
  const [jobs, setJobs] = useState([]);
  const [progressByJob, setProgressByJob] = useState({});
  const [selected, setSelected] = useState('');
  const [why, setWhy] = useState('');
  const [improve, setImprove] = useState('');
  const [previewJob, setPreviewJob] = useState(null);
  const [error, setError] = useState('');
  const [autoStarted, setAutoStarted] = useState(false);
  const [jobsLoaded, setJobsLoaded] = useState(false);

  async function refresh() {
    const allJobs = await client.jobs();
    const matchingJobs = allJobs
      .filter((job) => job.job_type === 'calibration_sample')
      .filter((job) => !activeChatId || job.chat_id === activeChatId)
      .filter((job) => !state.user_intent || job.topic.includes(state.user_intent));
    const latestBySample = new Map();
    for (const job of matchingJobs) {
      const slot = sampleNumber(job.topic);
      const previous = latestBySample.get(slot);
      if (!previous || new Date(job.created_at) > new Date(previous.created_at)) {
        latestBySample.set(slot, job);
      }
    }
    const calibrationJobs = [1, 2, 3]
      .map((slot) => latestBySample.get(slot))
      .filter(Boolean);
    setJobs(calibrationJobs);
    setJobsLoaded(true);
    return calibrationJobs;
  }

  async function refreshProgress(jobItems = jobs) {
    if (!jobItems.length) return;
    const entries = await Promise.all(jobItems.slice(0, 3).map(async (job) => {
      try {
        return [job.id, await client.jobProgress(job.id)];
      } catch (err) {
        return [job.id, { job_id: job.id, status: job.status, percent: 0, current_agent: '', agents: [], events: [], error_message: err.message }];
      }
    }));
    setProgressByJob(Object.fromEntries(entries));
  }

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
    const timer = setInterval(() => refresh().catch(console.error), 5000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!jobsLoaded || autoStarted || jobs.length > 0) return;
    setAutoStarted(true);
    start().catch((err) => setError(err.message));
  }, [autoStarted, jobs.length, jobsLoaded]);

  useEffect(() => {
    if (!jobs.length) return undefined;
    let cancelled = false;
    async function tick() {
      if (cancelled) return;
      await refreshProgress(jobs);
    }
    tick().catch(console.error);
    if (jobs.slice(0, 3).every((job) => TERMINAL_STATUSES.has(job.status))) {
      return () => {
        cancelled = true;
      };
    }
    const timer = setInterval(() => tick().catch(console.error), 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [jobs.map((job) => `${job.id}:${job.status}`).join('|')]);

  async function start() {
    setError('');
    try {
      const settings = defaultSettings();
      settings.image_count = 8;
      await client.startCalibration({ genre_id: state.genre_id, user_intent: state.user_intent, settings });
      const nextJobs = await refresh();
      await refreshProgress(nextJobs);
    } catch (err) {
      setError(err.message);
    }
  }

  async function complete() {
    setError('');
    try {
      await client.completeCalibration({ preferred_video_id: selected, why_chosen: why, improvement_notes: improve });
      await onDone();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <Shell user={user} onLogout={onLogout} client={client} onReset={onReset} page={page} onNavigate={onNavigate} activeChatId={activeChatId} onSelectChat={onSelectChat} onNewChat={onNewChat}>
      <section className="panel chat-workspace">
        <StepHeader step="Step 3" title="Calibration Chat" text="The agent is automatically creating three style samples from your intent. Pick the one closest to your taste." />
        {error && <p className="error">{error}</p>}
        <div className="chat-thread">
          <div className="chat-bubble user">
            <strong>Your intent</strong>
            <p>{state.user_intent}</p>
          </div>
          <div className="chat-bubble assistant">
            <strong>Studio agent</strong>
            <p>I am generating 3 calibration samples in parallel. Each card below tracks its own worker and agent progress.</p>
          </div>
        </div>
        <div className="loading-banner">
          <div>
            <p className="eyebrow">Parallel calibration</p>
            <h3>{jobs.length ? 'Three samples are rendering together' : 'Starting the three sample jobs...'}</h3>
            <p className="muted">Watch each agent move through script, assets, voice, captions, and render in real time.</p>
          </div>
          <span>{jobs.slice(0, 3).filter((job) => (progressByJob[job.id]?.status || job.status) === 'succeeded').length}/3 ready</span>
        </div>
        <div className="sample-grid">
          {jobs.length === 0 && [1, 2, 3].map((index) => (
            <article className="sample-card" key={index}>
              <span className="job-status queued">queued</span>
              <h3>Sample {index}</h3>
              <p>Waiting for job id...</p>
              <JobProgress />
            </article>
          ))}
          {jobs.map((job, index) => {
            const progress = progressByJob[job.id];
            const status = progress?.status || job.status;
            return (
              <article className={`sample-card ${selected === job.id ? 'selected' : ''}`} key={job.id}>
                <span className={`job-status ${status}`}>{status}</span>
                <h3>Sample {index + 1}</h3>
                <p>{job.topic}</p>
                <JobProgress client={client} jobId={job.id} progress={progress} />
                {job.preview_url && <button onClick={() => setPreviewJob(job)}>Preview</button>}
                <button className="ghost" disabled={status !== 'succeeded'} onClick={() => setSelected(job.id)}>Pick this style</button>
              </article>
            );
          })}
        </div>
        {selected && (
          <div className="feedback-box">
            <div>
              <p className="eyebrow">Preference memory</p>
              <h3>Tell the agent why this sample won</h3>
            </div>
            <textarea value={why} onChange={(event) => setWhy(event.target.value)} placeholder="Why did you pick this one?" />
            <textarea value={improve} onChange={(event) => setImprove(event.target.value)} placeholder="What could be improved?" />
            <button disabled={!why.trim()} onClick={complete}>Complete setup</button>
          </div>
        )}
      </section>
      {previewJob && <VideoPreview client={client} job={previewJob} onClose={() => setPreviewJob(null)} />}
    </Shell>
  );
}

function Dashboard({ client, user, state, onLogout, onReset, onNavigate, page = 'studio', activeChatId, onSelectChat, onNewChat }) {
  const [jobs, setJobs] = useState([]);
  const [genres, setGenres] = useState([]);
  const [messages, setMessages] = useState([]);
  const [chatText, setChatText] = useState('');
  const [sending, setSending] = useState(false);
  const [previewJob, setPreviewJob] = useState(null);
  const [error, setError] = useState('');
  const chatEndRef = useRef(null);

  async function refresh() {
    const [jobList, genreList, messageList] = await Promise.all([
      client.jobs(),
      client.genres(),
      activeChatId ? client.messages(activeChatId) : Promise.resolve([]),
    ]);
    setJobs(activeChatId ? jobList.filter((job) => job.chat_id === activeChatId) : jobList);
    setGenres(genreList);
    setMessages(messageList);
  }

  useEffect(() => {
    refresh().catch((err) => setError(err.message));
    const timer = setInterval(() => refresh().catch(console.error), 5000);
    return () => clearInterval(timer);
  }, [activeChatId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ block: 'end' });
  }, [messages.length, sending]);

  async function sendChat(event) {
    event.preventDefault();
    if (!activeChatId || !chatText.trim() || sending) return;
    setSending(true);
    setError('');
    try {
      await client.sendMessage(activeChatId, { content: chatText.trim() });
      setChatText('');
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  const finalJobs = jobs.filter((job) => job.job_type !== 'calibration_sample');
  const latestAssistantPlan = [...messages]
    .reverse()
    .find((message) => message.role === 'assistant' && message.message_metadata?.job_id)
    ?.message_metadata;
  const latestJob = latestAssistantPlan?.job_id
    ? finalJobs.find((job) => job.id === latestAssistantPlan.job_id)
    : finalJobs[0];
  const genreName = genres.find((genre) => genre.genre_id === state.genre_id)?.display_name || label(state.genre_id || 'selected_style');

  return (
    <Shell user={user} onLogout={onLogout} client={client} onReset={onReset} page={page} onNavigate={onNavigate} activeChatId={activeChatId} onSelectChat={onSelectChat} onNewChat={onNewChat}>
      <section className="dashboard continuous-dashboard">
        <div className="panel chat-console continuous-chat">
          <div className="chat-console-head">
            <StepHeader step="Studio Agent" title="Continuous Video Chat" text="Prompt the master agent for a new video or ask follow-up changes. It extracts the useful details and routes one production job from the current chat context." />
            <div className="context-pills" aria-label="Active context">
              <span>{genreName}</span>
              <span>Calibrated style locked</span>
              {latestJob && <span>Last video {shortId(latestJob.id)}</span>}
            </div>
          </div>
          <div className="prompt-chip-row" aria-label="Suggested prompts">
            {PROMPT_SUGGESTIONS.map((prompt) => (
              <button type="button" className="prompt-chip" key={prompt} onClick={() => setChatText(prompt)}>
                {prompt}
              </button>
            ))}
          </div>
          <div className="chat-log continuous-log" aria-live="polite">
            {messages.length === 0 && (
              <div className="chat-message assistant">
                <strong>Studio agent</strong>
                <p>Tell me the final short you want, or ask for a change to the last video. Example: make the voice faster and keep the same topic.</p>
              </div>
            )}
            {messages.map((message) => (
              <ChatMessageItem
                key={message.id}
                message={message}
                jobs={finalJobs}
                onPreview={(job) => setPreviewJob(job)}
              />
            ))}
            {sending && (
              <div className="chat-message assistant pending">
                <strong>Studio agent</strong>
                <p>Reading the prompt, extracting the route, and preparing the next step...</p>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
          <form className="chat-input-row" onSubmit={sendChat}>
            <textarea
              rows="2"
              value={chatText}
              onChange={(event) => setChatText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  sendChat(event);
                }
              }}
              placeholder={activeChatId ? 'Ask for a new video or a change: faster voice, more stock video, shorter duration...' : 'Create or select a chat to start'}
            />
            <button disabled={sending || !chatText.trim() || !activeChatId}>{sending ? 'Sending...' : 'Send'}</button>
          </form>
          {error && <p className="error">{error}</p>}
        </div>
        <div className="studio-side-panel">
          <div className="panel route-summary-panel">
            <StepHeader step="Current Route" title="Master Memory" text="The backend keeps the selected sample, previous job, and latest settings. Follow-up prompts layer onto that context." />
            {latestAssistantPlan ? (
              <MasterPlanPanel metadata={latestAssistantPlan} job={latestJob} onPreview={(job) => setPreviewJob(job)} compact />
            ) : (
              <p className="muted">No production route yet. Ask for one final video, then future messages can modify it.</p>
            )}
          </div>
          <div className="panel jobs-list">
            <StepHeader step="Preview" title="Videos" text="Preview, download, and save mistakes so the next prompt avoids them." />
            {finalJobs.slice(0, 12).map((job) => (
              <JobCard key={job.id} client={client} job={job} onPreview={() => setPreviewJob(job)} />
            ))}
            {finalJobs.length === 0 && <p className="muted">Generated videos from this chat will appear here.</p>}
          </div>
        </div>
      </section>
      {previewJob && <VideoPreview client={client} job={previewJob} onClose={() => setPreviewJob(null)} withFeedback />}
    </Shell>
  );
}

function ChatMessageItem({ message, jobs, onPreview }) {
  const metadata = message.message_metadata || {};
  const job = metadata.job_id ? jobs.find((item) => item.id === metadata.job_id) : null;
  return (
    <>
      <div className={`chat-message ${message.role}`}>
        <div className="chat-message-head">
          <strong>{message.role === 'user' ? 'You' : 'Studio agent'}</strong>
          <span>{formatDate(message.created_at)}</span>
        </div>
        <p>{message.content}</p>
        {metadata.job_id && <small>Queued video: {shortId(metadata.job_id)}</small>}
      </div>
      {message.role === 'assistant' && (
        <MasterPlanPanel metadata={metadata} job={job} onPreview={onPreview} />
      )}
    </>
  );
}

function MasterPlanPanel({ metadata = {}, job = null, onPreview, compact = false }) {
  const aiDecision = metadata.ai_master_decision || {};
  const settings = metadata.settings || aiDecision.settings || {};
  const constraints = metadata.constraints || {};
  const agents = metadata.planned_agents || metadata.agent_contracts || aiDecision.planned_agents || [];
  const intent = metadata.intent || aiDecision.intent || '';
  const topic = job?.topic || aiDecision.topic || '';
  const genre = job?.genre || aiDecision.genre || '';
  const settingsItems = buildSettingsItems(settings, constraints);
  const hasUsefulMetadata = Boolean(
    metadata.job_id
    || intent
    || topic
    || Object.keys(aiDecision).length
    || settingsItems.length
    || agents.length
  );

  if (!hasUsefulMetadata) return null;

  return (
    <div className={`master-plan-panel ${compact ? 'compact' : ''}`}>
      <div className="master-plan-head">
        <div>
          <p className="eyebrow">Master extraction</p>
          <h3>{formatIntent(intent)}</h3>
        </div>
        {job && <span className={`job-status ${job.status}`}>{job.status}</span>}
      </div>
      <div className="extraction-grid">
        {topic && <MetadataItem labelText="Topic" value={topic} />}
        {genre && <MetadataItem labelText="Genre" value={label(genre)} />}
        {settingsItems.map((item) => (
          <MetadataItem key={item.key} labelText={item.label} value={item.value} />
        ))}
      </div>
      {metadata.parent_job_id && (
        <p className="continuation-note">
          Continuing from video {shortId(metadata.parent_job_id)} with the new prompt layered on top.
        </p>
      )}
      {agents.length > 0 && (
        <div className="agent-route-mini" aria-label="Agent route">
          {agents.map((agent) => (
            <span key={agent.name || agent.label}>{agent.label || label(agent.name || 'agent')}</span>
          ))}
        </div>
      )}
      {job?.status === 'succeeded' && job.preview_url && (
        <button type="button" className="ghost small preview-result" onClick={() => onPreview?.(job)}>
          Preview result
        </button>
      )}
    </div>
  );
}

function MetadataItem({ labelText, value }) {
  return (
    <div className="metadata-item">
      <span>{labelText}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ControlGrid({ settings, setSettings }) {
  function update(key, value) {
    setSettings({ ...settings, [key]: value });
  }
  return (
    <div className="controls-grid">
      <label>Duration seconds<input type="number" min="10" max="180" step="1" value={settings.duration} onChange={(event) => update('duration', Number(event.target.value))} /></label>
      <label>Voice speed<input type="number" min="0.65" max="1.4" step="0.05" value={settings.voice_speed} onChange={(event) => update('voice_speed', Number(event.target.value))} /></label>
      <label>Caption words<input type="number" min="1" max="10" value={settings.caption_words} onChange={(event) => update('caption_words', Number(event.target.value))} /></label>
      <label>Visual cues<input type="number" min="3" max="24" value={settings.image_count} onChange={(event) => update('image_count', Number(event.target.value))} /></label>
      <label>Music volume<input type="number" min="0" max="0.8" step="0.02" value={settings.music_volume} onChange={(event) => update('music_volume', Number(event.target.value))} /></label>
      <SelectField
        label="Schedule"
        value={settings.schedule}
        onChange={(value) => update('schedule', value)}
        options={[
          { value: 'now', label: 'Now' },
          { value: 'best_time', label: 'Best time' },
        ]}
      />
    </div>
  );
}

function JobCard({ client, job, onPreview }) {
  const [progress, setProgress] = useState(null);

  useEffect(() => {
    if (TERMINAL_STATUSES.has(job.status)) return undefined;
    let cancelled = false;
    async function tick() {
      try {
        const nextProgress = await client.jobProgress(job.id);
        if (!cancelled) setProgress(nextProgress);
      } catch (err) {
        if (!cancelled) setProgress({ job_id: job.id, status: job.status, percent: 0, current_agent: '', agents: [], events: [], error_message: err.message });
      }
    }
    tick();
    const timer = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [job.id, job.status]);

  return (
    <article className="job-card">
      <div>
        <strong>{job.topic}</strong>
        <small>{label(job.genre)} · {job.duration}s · {job.settings?.image_count || 'auto'} visual cues</small>
        {job.parent_job_id && <small>Updated from {shortId(job.parent_job_id)}</small>}
      </div>
      <span className={`job-status ${job.status}`}>{job.status}</span>
      {(job.status === 'queued' || job.status === 'running') && <JobProgress client={client} jobId={job.id} progress={progress} compact />}
      {job.status === 'succeeded' && <button onClick={onPreview}>Preview</button>}
      {job.error_message && <p className="error">{job.error_message}</p>}
    </article>
  );
}

function JobProgress({ client, jobId, progress, compact = false }) {
  const agents = progress?.agents || [];
  const current = agents.find((agent) => agent.name === progress?.current_agent);
  const latestEvents = (progress?.events || []).slice(-3).reverse();
  const percent = Math.max(0, Math.min(100, progress?.percent || 0));
  const isQueued = progress?.status === 'queued';
  const [logsOpen, setLogsOpen] = useState(false);
  const [logs, setLogs] = useState(null);
  const [logsError, setLogsError] = useState('');

  async function toggleLogs() {
    const nextOpen = !logsOpen;
    setLogsOpen(nextOpen);
    if (!nextOpen || !client || !jobId || logs) return;
    setLogsError('');
    try {
      setLogs(await client.jobLogs(jobId));
    } catch (err) {
      setLogsError(err.message);
    }
  }

  if (!progress) {
    return (
      <div className={`job-progress ${compact ? 'compact' : ''}`}>
        <div className="progress-head">
          <span>Waiting for worker</span>
          <strong>0%</strong>
        </div>
        <div className="progress-bar"><span style={{ width: '4%' }} /></div>
      </div>
    );
  }

  return (
    <div className={`job-progress ${compact ? 'compact' : ''}`}>
      <div className="progress-head">
        <span>{isQueued ? 'Queued for a worker' : current ? `${current.label} agent is working` : progress.status}</span>
        <strong>{percent}%</strong>
      </div>
      <div className="progress-bar"><span style={{ width: `${Math.max(percent, progress.status === 'running' ? 8 : 4)}%` }} /></div>
      {agents.length > 0 && (
        <div className="agent-rail">
          {agents.map((agent) => (
            <span className={`agent-pill ${agent.status}`} key={agent.name}>
              {agent.label}
            </span>
          ))}
        </div>
      )}
      {!isQueued && current?.message && <p className="agent-message">{current.message}</p>}
      {latestEvents.length > 0 && (
        <div className="event-feed">
          {latestEvents.map((event, index) => (
            <small key={`${event.ts || 'event'}-${index}`}>
              <strong>{label(String(event.module || event.stage || 'agent'))}</strong>
              {event.message || event.error_type || 'Working...'}
            </small>
          ))}
        </div>
      )}
      {progress.error_message && <p className="error">{progress.error_message}</p>}
      {client && jobId && (
        <button className="ghost small log-toggle" onClick={toggleLogs}>{logsOpen ? 'Hide logs' : 'Show full logs'}</button>
      )}
      {logsOpen && (
        <div className="full-log-panel">
          {logsError && <p className="error">{logsError}</p>}
          {!logs && !logsError && <p className="muted">Loading logs...</p>}
          {logs?.events?.map((event, index) => (
            <pre key={`${event.ts || 'event'}-${index}`}>{`${event.ts || ''} ${event.module || event.stage || 'agent'}: ${event.message || event.error_type || ''}`}</pre>
          ))}
          {logs?.error_message && <pre className="error">{logs.error_message}</pre>}
          {logs?.stdout && <pre>{logs.stdout}</pre>}
          {logs?.stderr && <pre>{logs.stderr}</pre>}
        </div>
      )}
    </div>
  );
}

function VideoPreview({ client, job, onClose, withFeedback = false }) {
  const [videoUrl, setVideoUrl] = useState('');
  const [shortsCoverUrl, setShortsCoverUrl] = useState('');
  const [youtubeThumbUrl, setYoutubeThumbUrl] = useState('');
  const [downloadError, setDownloadError] = useState('');
  const [selectedIssues, setSelectedIssues] = useState([]);
  const [notes, setNotes] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let objectUrl = '';
    let shortsUrl = '';
    let youtubeUrl = '';
    client.blob(job.preview_url).then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      setVideoUrl(objectUrl);
    }).catch((err) => setDownloadError(err.message));
    if (job.shorts_cover_url) {
      client.blob(job.shorts_cover_url).then((blob) => {
        shortsUrl = URL.createObjectURL(blob);
        setShortsCoverUrl(shortsUrl);
      }).catch(() => {});
    }
    if (job.youtube_thumbnail_url) {
      client.blob(job.youtube_thumbnail_url).then((blob) => {
        youtubeUrl = URL.createObjectURL(blob);
        setYoutubeThumbUrl(youtubeUrl);
      }).catch(() => {});
    }
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      if (shortsUrl) URL.revokeObjectURL(shortsUrl);
      if (youtubeUrl) URL.revokeObjectURL(youtubeUrl);
    };
  }, [job.id]);

  async function downloadArtifact(urlPath, filename) {
    setDownloadError('');
    try {
      const blob = await client.blob(urlPath);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setDownloadError(err.message);
    }
  }

  async function submitFeedback() {
    await client.saveFeedback(job.id, { issue_types: selectedIssues, notes });
    setSaved(true);
  }

  function toggleIssue(issue) {
    setSelectedIssues(selectedIssues.includes(issue)
      ? selectedIssues.filter((item) => item !== issue)
      : [...selectedIssues, issue]);
  }

  return (
    <div className="modal-backdrop">
      <section className="preview-modal">
        <div className="modal-head">
          <h2>{job.topic}</h2>
          <button className="ghost small" onClick={onClose}>Close</button>
        </div>
        {videoUrl ? <video src={videoUrl} controls className="video-player" /> : <p className="muted">Loading preview...</p>}
      {downloadError && <p className="error">{downloadError}</p>}
        <div className="artifact-actions">
          <button onClick={() => downloadArtifact(job.download_url, `${job.id}.mp4`)}>Download video</button>
          {job.shorts_cover_url && <button className="ghost" onClick={() => downloadArtifact(job.shorts_cover_url, `${job.id}_shorts_cover.jpg`)}>Shorts cover</button>}
          {job.youtube_thumbnail_url && <button className="ghost" onClick={() => downloadArtifact(job.youtube_thumbnail_url, `${job.id}_youtube_thumbnail.jpg`)}>YouTube thumbnail</button>}
          {job.render_plan_url && <button className="ghost" onClick={() => downloadArtifact(job.render_plan_url, `${job.id}_render_plan.json`)}>Render plan</button>}
        </div>
        {(shortsCoverUrl || youtubeThumbUrl) && (
          <div className="thumbnail-preview-grid">
            {shortsCoverUrl && (
              <figure>
                <img src={shortsCoverUrl} alt="Shorts cover" />
                <figcaption>Shorts cover</figcaption>
              </figure>
            )}
            {youtubeThumbUrl && (
              <figure>
                <img src={youtubeThumbUrl} alt="YouTube thumbnail" />
                <figcaption>YouTube thumbnail</figcaption>
              </figure>
            )}
          </div>
        )}
        {withFeedback && (
          <div className="feedback-box">
            <h3>What changes or mistakes do you find?</h3>
            <div className="issue-grid">
              {ISSUE_TYPES.map(([value, text]) => (
                <button key={value} className={selectedIssues.includes(value) ? '' : 'ghost'} onClick={() => toggleIssue(value)}>{text}</button>
              ))}
            </div>
            <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Example: stock video repeated too much, voice too fast, captions covered the scene..." />
            <button disabled={saved || (!notes.trim() && selectedIssues.length === 0)} onClick={submitFeedback}>{saved ? 'Saved for next time' : 'Save feedback memory'}</button>
          </div>
        )}
      </section>
    </div>
  );
}

function StepHeader({ step, title, text }) {
  return (
    <div className="step-header">
      <p className="eyebrow">{step}</p>
      <h2>{title}</h2>
      <p className="muted">{text}</p>
    </div>
  );
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6Zm0-5 1.5 2.4c.5.1 1 .3 1.5.6l2.7-.6 1.8 3.1-1.8 2.1c.1.5.1 1.1 0 1.6l1.8 2.1-1.8 3.1-2.7-.6c-.5.3-1 .5-1.5.6L12 20.8 10.5 18c-.5-.1-1-.3-1.5-.6l-2.7.6-1.8-3.1 1.8-2.1a7 7 0 0 1 0-1.6L4.5 8.7l1.8-3.1 2.7.6c.5-.3 1-.5 1.5-.6L12 3.2Z" />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6.7 8.8 12 14l5.3-5.2 1.4 1.4L12 16.9 5.3 10.2l1.4-1.4Z" />
    </svg>
  );
}

function NewChatIcon({ spinning = false }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={spinning ? 'spin' : ''}>
      <path d="M5 4.5A2.5 2.5 0 0 1 7.5 2h7A2.5 2.5 0 0 1 17 4.5V10h-2V4.5a.5.5 0 0 0-.5-.5h-7a.5.5 0 0 0-.5.5v11a.5.5 0 0 0 .5.5H12v2H7.5A2.5 2.5 0 0 1 5 15.5v-11Z" />
      <path d="M18 12v3h3v2h-3v3h-2v-3h-3v-2h3v-3h2Z" />
    </svg>
  );
}

function SidebarIcon({ open = true }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm5 2v12h11V6H9ZM4 6v12h3V6H4Z" />
      <path d={open ? "M14.8 8.8 12.6 12l2.2 3.2h-2.3L10.3 12l2.2-3.2h2.3Z" : "M11.2 8.8h2.3l2.2 3.2-2.2 3.2h-2.3l2.2-3.2-2.2-3.2Z"} />
    </svg>
  );
}

function formatDate(value) {
  if (!value) return '';
  return new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function sampleNumber(topic = '') {
  const match = String(topic).match(/sample\s+(\d+)/i);
  return match ? Number(match[1]) : 999;
}

function buildSettingsItems(settings = {}, constraints = {}) {
  const values = {
    duration: settings.duration ?? constraints.duration_seconds,
    voice_speed: settings.voice_speed ?? constraints.voice_speed_multiplier,
    image_count: settings.image_count ?? constraints.image_count,
    caption_words: settings.caption_words ?? constraints.caption_words_per_phrase,
    music_volume: settings.music_volume ?? constraints.music_volume,
    schedule: settings.schedule ?? constraints.schedule,
  };
  return SETTING_ORDER
    .filter((key) => values[key] !== undefined && values[key] !== null && values[key] !== '')
    .map((key) => ({
      key,
      label: SETTING_LABELS[key] || label(key),
      value: formatSettingValue(key, values[key]),
    }));
}

function formatSettingValue(key, value) {
  if (key === 'duration') return `${Number(value)}s`;
  if (key === 'voice_speed') return `${Number(value)}x`;
  if (key === 'image_count') return `${Number(value)} visual cues`;
  if (key === 'caption_words') return `${Number(value)} words`;
  if (key === 'music_volume') return `${Math.round(Number(value) * 100)}%`;
  if (key === 'schedule') return label(String(value));
  return String(value);
}

function formatIntent(intent = '') {
  const normalized = String(intent || '').trim();
  if (normalized === 'generate_video') return 'Generation queued';
  if (normalized === 'ask_clarifying_question') return 'Needs one detail';
  if (normalized === 'save_preference') return 'Preference saved';
  if (normalized === 'chat') return 'Chat reply';
  return normalized ? label(normalized) : 'Route extracted';
}

function shortId(value = '') {
  return String(value || '').slice(0, 8);
}

function label(provider) {
  if (!provider) return '';
  if (PROVIDER_LABELS[provider]) return PROVIDER_LABELS[provider];
  return String(provider).replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

createRoot(document.getElementById('root')).render(<App />);
