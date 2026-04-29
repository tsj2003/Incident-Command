import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, AlertTriangle, CheckCircle2, Clock, Database, Radio, RefreshCcw, Send, ShieldCheck, Sparkles } from 'lucide-react';
import './styles.css';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const statuses = ['OPEN', 'INVESTIGATING', 'RESOLVED', 'CLOSED'];
const nextStatus = {
  OPEN: 'INVESTIGATING',
  INVESTIGATING: 'RESOLVED',
  RESOLVED: 'CLOSED',
  CLOSED: null,
};
const categories = ['Database failover', 'Capacity saturation', 'Bad deploy', 'Network partition', 'Dependency outage', 'Configuration drift'];

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : '-';
}

function toLocalInput(value) {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function severityClass(severity) {
  return `severity ${severity.toLowerCase()}`;
}

function App() {
  const [incidents, setIncidents] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [health, setHealth] = useState(null);
  const [error, setError] = useState('');

  async function loadIncidents() {
    const response = await fetch(`${API_BASE}/incidents`);
    if (!response.ok) throw new Error('Unable to load incidents');
    const data = await response.json();
    setIncidents(data);
    if (!selectedId && data.length) setSelectedId(data[0].id);
  }

  async function loadHealth() {
    const response = await fetch(`${API_BASE}/health`);
    if (response.ok) setHealth(await response.json());
  }

  async function loadDetail(id = selectedId) {
    if (!id) return;
    const response = await fetch(`${API_BASE}/incidents/${id}`);
    if (!response.ok) throw new Error('Unable to load incident detail');
    setDetail(await response.json());
  }

  useEffect(() => {
    loadIncidents().catch((err) => setError(err.message));
    loadHealth();
    const timer = setInterval(() => {
      loadIncidents().catch((err) => setError(err.message));
      loadHealth();
      if (selectedId) loadDetail(selectedId).catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [selectedId]);

  useEffect(() => {
    loadDetail(selectedId).catch((err) => selectedId && setError(err.message));
  }, [selectedId]);

  const p0Count = useMemo(() => incidents.filter((item) => item.severity === 'P0').length, [incidents]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark"><Radio size={18} /></span>
          <div>
            <p className="eyebrow">Mission-Critical IMS</p>
            <h1>Incident Command</h1>
          </div>
        </div>
        <div className="health-strip">
          <span><Activity size={16} /> {health?.status || 'checking'}</span>
          <span><Clock size={16} /> Queue {health?.queue_depth ?? '-'}/{health?.queue_capacity ?? 25000}</span>
          <span><Database size={16} /> Batch {health?.pending_batch ?? '-'}</span>
          <button onClick={() => { loadIncidents(); loadDetail(); }} title="Refresh dashboard">
            <RefreshCcw size={17} />
          </button>
        </div>
      </header>

      {error && <button className="error" onClick={() => setError('')}>{error}</button>}

      <section className="command-hero">
        <div className="hero-copy">
          <p className="eyebrow">Live distributed systems control plane</p>
          <h2>Catch the burst, group the noise, close with proof.</h2>
        </div>
        <div className="hero-stats">
          <Metric icon={<AlertTriangle size={17} />} label="P0 Active" value={p0Count} />
          <Metric icon={<ShieldCheck size={17} />} label="Dropped" value={health?.dropped ?? 0} />
          <Metric icon={<Sparkles size={17} />} label="Uptime" value={health?.uptime_seconds ? `${Math.floor(health.uptime_seconds / 60)}m` : '-'} />
        </div>
      </section>

      <section className="dashboard-grid">
        <aside className="feed-panel">
          <div className="panel-heading">
            <h2>Live Feed</h2>
            <span>{incidents.length} active</span>
          </div>
          <div className="incident-list">
            {incidents.map((incident) => (
              <button
                key={incident.id}
                className={`incident-row ${incident.id === selectedId ? 'selected' : ''}`}
                onClick={() => setSelectedId(incident.id)}
              >
                <span className={severityClass(incident.severity)}>{incident.severity}</span>
                <span className="incident-main">
                  <strong>{incident.component_id}</strong>
                  <small>{incident.service} · {incident.status}</small>
                </span>
                <span className="signal-count">{incident.signal_count}</span>
              </button>
            ))}
            {!incidents.length && <div className="empty">No active incidents.</div>}
          </div>
        </aside>

        <section className="detail-panel">
          {detail ? (
            <>
              <div className="detail-header">
                <div>
                  <p className="eyebrow">{detail.incident.component_type}</p>
                  <h2>{detail.incident.component_id}</h2>
                </div>
                <span className={severityClass(detail.incident.severity)}>{detail.incident.severity}</span>
              </div>

              <div className="metrics-row">
                <Metric label="Status" value={detail.incident.status} />
                <Metric label="Signals" value={detail.incident.signal_count} />
                <Metric label="First Signal" value={formatDate(detail.incident.first_signal_at)} />
                <Metric label="MTTR" value={detail.incident.mttr_seconds ? `${Math.round(detail.incident.mttr_seconds / 60)}m` : '-'} />
              </div>

              <StatusControls incident={detail.incident} onDone={() => { loadIncidents(); loadDetail(detail.incident.id); }} setError={setError} />
              <RcaForm incident={detail.incident} existing={detail.rca} onDone={() => loadDetail(detail.incident.id)} setError={setError} />
              <AuditTimeline events={detail.audit_events || []} />
              <SignalTable signals={detail.signals} />
            </>
          ) : (
            <div className="empty detail-empty">Select an incident to inspect raw signals and RCA.</div>
          )}
        </section>
      </section>
    </main>
  );
}

function Metric({ icon, label, value }) {
  return (
    <div className="metric">
      <small>{icon}{label}</small>
      <strong>{value}</strong>
    </div>
  );
}

function StatusControls({ incident, onDone, setError }) {
  const allowedNext = nextStatus[incident.status];

  async function updateStatus(status) {
    const response = await fetch(`${API_BASE}/incidents/${incident.id}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
    });
    if (!response.ok) {
      const body = await response.json();
      setError(body.detail || 'Status update failed');
      return;
    }
    onDone();
  }

  return (
    <div className="toolbar">
      {statuses.map((status) => (
        <button
          key={status}
          disabled={incident.status === status || status !== allowedNext}
          onClick={() => updateStatus(status)}
          title={status === allowedNext ? `Move to ${status}` : 'Unavailable in the forward-only workflow'}
        >
          {status === 'CLOSED' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          {status}
        </button>
      ))}
    </div>
  );
}

function AuditTimeline({ events }) {
  return (
    <section className="timeline-panel">
      <div className="panel-heading">
        <h2>Incident Timeline</h2>
        <span>{events.length} events</span>
      </div>
      <div className="timeline-list">
        {events.map((event) => (
          <div className="timeline-row" key={event.id}>
            <span className="timeline-dot" />
            <div>
              <strong>{event.event_type.replace('_', ' ')}</strong>
              <p>{event.message}</p>
              <small>{formatDate(event.created_at)}</small>
            </div>
          </div>
        ))}
        {!events.length && <div className="empty">No workflow events yet.</div>}
      </div>
    </section>
  );
}

function RcaForm({ incident, existing, onDone, setError }) {
  const [form, setForm] = useState({
    incident_start: toLocalInput(existing?.incident_start || incident.first_signal_at),
    incident_end: toLocalInput(existing?.incident_end || new Date().toISOString()),
    root_cause_category: existing?.root_cause_category || categories[0],
    fix_applied: existing?.fix_applied || '',
    prevention_steps: existing?.prevention_steps || '',
  });

  useEffect(() => {
    setForm({
      incident_start: toLocalInput(existing?.incident_start || incident.first_signal_at),
      incident_end: toLocalInput(existing?.incident_end || new Date().toISOString()),
      root_cause_category: existing?.root_cause_category || categories[0],
      fix_applied: existing?.fix_applied || '',
      prevention_steps: existing?.prevention_steps || '',
    });
  }, [incident.id, existing]);

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    const response = await fetch(`${API_BASE}/incidents/${incident.id}/rca`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...form,
        incident_start: new Date(form.incident_start).toISOString(),
        incident_end: new Date(form.incident_end).toISOString(),
      }),
    });
    if (!response.ok) {
      const body = await response.json();
      setError(body.detail || 'RCA submission failed');
      return;
    }
    onDone();
  }

  return (
    <form className="rca-form" onSubmit={submit}>
      <div className="panel-heading">
        <h2>Root Cause Analysis</h2>
        {existing && <span>Submitted · MTTR {Math.round(existing.mttr_seconds / 60)}m</span>}
      </div>
      <div className="form-grid">
        <label>Incident Start<input type="datetime-local" value={form.incident_start} onChange={(e) => update('incident_start', e.target.value)} required /></label>
        <label>Incident End<input type="datetime-local" value={form.incident_end} onChange={(e) => update('incident_end', e.target.value)} required /></label>
        <label>Root Cause Category<select value={form.root_cause_category} onChange={(e) => update('root_cause_category', e.target.value)}>{categories.map((category) => <option key={category}>{category}</option>)}</select></label>
      </div>
      <label>Fix Applied<textarea value={form.fix_applied} onChange={(e) => update('fix_applied', e.target.value)} required /></label>
      <label>Prevention Steps<textarea value={form.prevention_steps} onChange={(e) => update('prevention_steps', e.target.value)} required /></label>
      <button className="primary-action" type="submit"><Send size={16} /> Submit RCA</button>
    </form>
  );
}

function SignalTable({ signals }) {
  return (
    <section className="signal-panel">
      <div className="panel-heading">
        <h2>Raw Signals</h2>
        <span>{signals.length} linked</span>
      </div>
      <div className="signal-table">
        {signals.slice().reverse().map((signal) => (
          <div className="signal-row" key={signal.id}>
            <span>{formatDate(signal.received_at)}</span>
            <strong>{signal.error_code}</strong>
            <span>{signal.message}</span>
          </div>
        ))}
        {!signals.length && <div className="empty">Signals are still draining from the async queue.</div>}
      </div>
    </section>
  );
}

createRoot(document.getElementById('root')).render(<App />);
