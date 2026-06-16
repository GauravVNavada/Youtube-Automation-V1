import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API_BASE = '/api/playground';
const TERMINAL = new Set(['succeeded', 'failed']);

function SelectField({ label, value, options, onChange, placeholder = 'Select option' }) {
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

  return (
    <label className="ui-field" htmlFor={id} ref={ref}>
      <span>{label}</span>
      <button
        id={id}
        type="button"
        className={`ui-select-trigger ${open ? 'open' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
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
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
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

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function App() {
  const [message, setMessage] = useState('');
  const [runs, setRuns] = useState([]);
  const [genres, setGenres] = useState([]);
  const [llmOptions, setLlmOptions] = useState([]);
  const [genreId, setGenreId] = useState('scary_stories');
  const [llmProvider, setLlmProvider] = useState('env');
  const [llmModel, setLlmModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [activeRun, setActiveRun] = useState(null);
  const [selectedStageId, setSelectedStageId] = useState('');
  const [stageDetail, setStageDetail] = useState(null);
  const [tab, setTab] = useState('overview');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function loadRuns() {
    const items = await request('/runs');
    setRuns(items);
    if (!activeRun && items.length) {
      await loadRun(items[0].id);
    }
  }

  async function loadSetup() {
    const [genreItems, llmItems] = await Promise.all([
      request('/genres'),
      request('/llm-options'),
    ]);
    setGenres(genreItems);
    setLlmOptions(llmItems);
    if (genreItems.length && !genreItems.some((genre) => genre.genre_id === genreId)) {
      setGenreId(genreItems[0].genre_id);
    }
  }

  async function loadRun(runId) {
    const run = await request(`/runs/${runId}`);
    setActiveRun(run);
    if (!selectedStageId && run.stages.length) {
      setSelectedStageId(run.stages[0].id);
    }
    return run;
  }

  async function submit(event) {
    event.preventDefault();
    if (!message.trim() || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const run = await request('/runs', {
        method: 'POST',
        body: JSON.stringify({
          message: message.trim(),
          genre_id: genreId,
          llm_provider: llmProvider,
          llm_model: llmModel,
          llm_api_key: apiKey,
        }),
      });
      setMessage('');
      setActiveRun(run);
      setSelectedStageId(run.stages[0]?.id || '');
      await loadRuns();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    loadSetup().catch((err) => setError(err.message));
    loadRuns().catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    const option = llmOptions.find((item) => item.provider === llmProvider);
    if (!option) return;
    setLlmModel(option.default_model || '');
  }, [llmProvider, llmOptions.length]);

  useEffect(() => {
    if (!activeRun || TERMINAL.has(activeRun.status)) return undefined;
    const timer = setInterval(() => {
      loadRun(activeRun.id).catch((err) => setError(err.message));
      loadRuns().catch(console.error);
    }, 1500);
    return () => clearInterval(timer);
  }, [activeRun?.id, activeRun?.status]);

  useEffect(() => {
    if (!activeRun || !selectedStageId) {
      setStageDetail(null);
      return undefined;
    }
    let cancelled = false;
    request(`/runs/${activeRun.id}/stages/${selectedStageId}`)
      .then((detail) => {
        if (!cancelled) setStageDetail(detail);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [activeRun?.id, selectedStageId, activeRun?.updated_at]);

  const selectedStage = useMemo(
    () => activeRun?.stages?.find((stage) => stage.id === selectedStageId),
    [activeRun, selectedStageId],
  );

  return (
    <main className="app">
      <aside className="sidebar">
        <div className="brand">
          <p>AI Agent</p>
          <h1>Playground</h1>
        </div>
        <form className="chat-card" onSubmit={submit}>
          <SelectField
            label="Genre"
            value={genreId}
            onChange={setGenreId}
            options={genres.map((genre) => ({ value: genre.genre_id, label: genre.display_name }))}
          />
          <SelectField
            label="AI provider"
            value={llmProvider}
            onChange={setLlmProvider}
            options={llmOptions.map((option) => ({ value: option.provider, label: option.label }))}
          />
          {llmProvider !== 'env' && (
            <>
              <SelectField
                label="Model"
                value={llmModel}
                onChange={setLlmModel}
                options={(llmOptions.find((option) => option.provider === llmProvider)?.models || []).map((model) => ({ value: model, label: model }))}
              />
              <label>API key for this run</label>
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder="Optional. If blank, Docker/.env key is used."
              />
            </>
          )}
          <label>Test message</label>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Try: make a 15 sec scary story about a leaked exam paper, slower voice, 12 images"
          />
          <button disabled={submitting || !message.trim()}>{submitting ? 'Starting...' : 'Run agents'}</button>
          {error && <p className="error">{error}</p>}
        </form>
        <section className="history">
          <div className="section-title">
            <span>Latest runs</span>
            <button className="ghost" onClick={() => loadRuns().catch((err) => setError(err.message))}>Refresh</button>
          </div>
          {runs.map((run) => (
            <button
              key={run.id}
              className={`run-item ${run.id === activeRun?.id ? 'active' : ''}`}
              onClick={() => {
                setSelectedStageId('');
                loadRun(run.id).catch((err) => setError(err.message));
              }}
            >
              <strong>{run.user_message}</strong>
              <small>{run.status} · {formatDate(run.created_at)}</small>
            </button>
          ))}
          {!runs.length && <p className="muted">No playground runs yet.</p>}
        </section>
      </aside>

      <section className="workspace">
        <header className="run-header">
          <div>
            <p className="eyebrow">Run graph</p>
            <h2>{activeRun ? activeRun.route_summary : 'Start a run to inspect agent flow'}</h2>
          </div>
          {activeRun && <span className={`status ${activeRun.status}`}>{activeRun.status}</span>}
        </header>
        {activeRun ? (
          <Graph
            stages={activeRun.stages}
            selectedStageId={selectedStageId}
            onSelect={(stage) => {
              setSelectedStageId(stage.id);
              setTab('overview');
            }}
          />
        ) : (
          <div className="empty-state">Type a message to create the first playground run.</div>
        )}
        <StagePanel stage={stageDetail || selectedStage} tab={tab} setTab={setTab} />
      </section>
    </main>
  );
}

function Graph({ stages, selectedStageId, onSelect }) {
  return (
    <section className="graph-shell">
      <div className="graph-line" />
      {stages.map((stage, index) => (
        <button
          key={stage.id}
          className={`graph-node ${stage.status} ${stage.id === selectedStageId ? 'selected' : ''}`}
          onClick={() => onSelect(stage)}
          style={{ '--index': index }}
        >
          <span>{index + 1}</span>
          <strong>{label(stage.agent_name)}</strong>
          <ModePill mode={stage.execution_mode} />
          <small>{stage.status}</small>
        </button>
      ))}
    </section>
  );
}

function StagePanel({ stage, tab, setTab }) {
  if (!stage) {
    return <section className="detail-panel empty-state">Select a graph node to inspect details.</section>;
  }
  const tabs = ['overview', 'input', 'prompt', 'output', 'logs', 'artifacts'];
  return (
    <section className="detail-panel">
      <div className="detail-head">
        <div>
          <p className="eyebrow">Selected node</p>
          <h2>{label(stage.agent_name)}</h2>
        </div>
        <div className="detail-badges">
          <ModePill mode={stage.execution_mode} />
          <span className={`status ${stage.status}`}>{stage.status}</span>
        </div>
      </div>
      <nav className="tabs">
        {tabs.map((item) => (
          <button key={item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)}>
            {item}
          </button>
        ))}
      </nav>
      {tab === 'overview' && (
        <div className="detail-content">
          <Info label="Started" value={formatDate(stage.started_at)} />
          <Info label="Completed" value={formatDate(stage.completed_at)} />
          <Info label="Execution source" value={modeDescription(stage.execution_mode)} />
          <Info label="Error" value={stage.error_text || 'None'} />
        </div>
      )}
      {tab === 'input' && <JsonBlock value={stage.input_json || {}} />}
      {tab === 'prompt' && <TextBlock value={stage.prompt_text || 'No prompt captured for this stage.'} />}
      {tab === 'output' && <JsonBlock value={stage.output_json || {}} />}
      {tab === 'logs' && <Logs events={stage.events || []} />}
      {tab === 'artifacts' && <Artifacts artifacts={stage.artifacts || []} />}
    </section>
  );
}

function Info({ label: name, value }) {
  return (
    <div className="info-row">
      <span>{name}</span>
      <strong>{value || 'Not available'}</strong>
    </div>
  );
}

function JsonBlock({ value }) {
  return <pre className="code-block">{JSON.stringify(value, null, 2)}</pre>;
}

function TextBlock({ value }) {
  return <pre className="code-block">{value}</pre>;
}

function Logs({ events }) {
  if (!events.length) return <p className="muted">No logs captured yet.</p>;
  return (
    <div className="log-list">
      {events.map((event) => (
        <div className={`log-row ${event.level}`} key={event.id}>
          <div className="log-meta">
            <strong>{formatDate(event.timestamp)}</strong>
            <ModePill mode={event.payload_json?.execution_mode} compact />
          </div>
          <span>{event.message}</span>
          <pre>{JSON.stringify(event.payload_json || {}, null, 2)}</pre>
        </div>
      ))}
    </div>
  );
}

function Artifacts({ artifacts }) {
  if (!artifacts.length) return <p className="muted">No files captured for this node yet.</p>;
  return (
    <div className="artifact-grid">
      {artifacts.map((artifact) => (
        <ArtifactPreview key={artifact.id} artifact={artifact} />
      ))}
    </div>
  );
}

function ArtifactPreview({ artifact }) {
  const [text, setText] = useState('');
  const url = `${API_BASE}/artifacts/${artifact.id}`;
  useEffect(() => {
    if (!artifact.previewable || !['json', 'text'].includes(artifact.kind)) return undefined;
    let cancelled = false;
    fetch(url)
      .then((response) => response.text())
      .then((value) => {
        if (!cancelled) setText(value);
      })
      .catch(() => {
        if (!cancelled) setText('Unable to load text preview.');
      });
    return () => {
      cancelled = true;
    };
  }, [artifact.id]);

  return (
    <article className="artifact-card">
      <div>
        <strong>{basename(artifact.path)}</strong>
        <small>{artifact.kind} · {formatBytes(artifact.size_bytes)}</small>
      </div>
      {artifact.kind === 'image' && <img src={url} alt={basename(artifact.path)} />}
      {artifact.kind === 'audio' && <audio controls src={url} />}
      {artifact.kind === 'video' && <video controls src={url} />}
      {['json', 'text'].includes(artifact.kind) && <pre>{text || 'Loading preview...'}</pre>}
      {!artifact.previewable && <p className="muted">Preview unavailable for this file type.</p>}
      <a href={url} target="_blank" rel="noreferrer">Open file</a>
    </article>
  );
}

function ModePill({ mode, compact = false }) {
  const normalized = normalizeMode(mode);
  if (!normalized) return null;
  return <em className={`mode-pill ${normalized} ${compact ? 'compact' : ''}`}>{modeLabel(normalized)}</em>;
}

function normalizeMode(value = '') {
  const normalized = String(value || '').trim().toLowerCase().replaceAll(' ', '_');
  return ['ai', 'hybrid', 'deterministic', 'fallback'].includes(normalized) ? normalized : '';
}

function modeLabel(mode) {
  return {
    ai: 'AI',
    hybrid: 'Hybrid',
    deterministic: 'Deterministic',
    fallback: 'Fallback',
  }[normalizeMode(mode)] || '';
}

function modeDescription(mode) {
  return {
    ai: 'AI worked here through the selected LLM provider.',
    hybrid: 'AI and deterministic code both worked here.',
    deterministic: 'Deterministic code, free sources, or local tools worked here.',
    fallback: 'A deterministic fallback handled this after another method failed.',
  }[normalizeMode(mode)] || 'Not available';
}

function label(value = '') {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function ChevronDownIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6.7 8.8 12 14l5.3-5.2 1.4 1.4L12 16.9 5.3 10.2l1.4-1.4Z" />
    </svg>
  );
}

function basename(path = '') {
  return path.split('/').pop() || path;
}

function formatDate(value) {
  if (!value) return '';
  return new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatBytes(value = 0) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

createRoot(document.getElementById('root')).render(<App />);
