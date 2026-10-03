import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const SEEDED_USERS = [
  { id: 'alice', label: 'Alice (Acme Corp · Admin · restricted)' },
  { id: 'bob', label: 'Bob (Acme Corp · HR · restricted)' },
  { id: 'carol', label: 'Carol (Acme Corp · Finance · confidential)' },
  { id: 'dave', label: 'Dave (Acme Corp · Employee · internal)' },
  { id: 'frank', label: 'Frank (Globex Inc · Admin · restricted)' },
];

function App() {
  const [user, setUser] = useState('bob');
  const [token, setToken] = useState('');
  const [question, setQuestion] = useState('What is the salary band for engineers?');
  const [answer, setAnswer] = useState(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState('chat');
  const [comparison, setComparison] = useState([]);
  const [logs, setLogs] = useState([]);
  const [filter, setFilter] = useState('');
  const [docId, setDocId] = useState('salary-acme-doc');
  const [whoSaw, setWhoSaw] = useState([]);
  const [verifyStatus, setVerifyStatus] = useState(null);

  async function login(username = user) {
    const response = await fetch('/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password: username }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Login failed');
    setToken(data.access_token);
    return data.access_token;
  }

  async function ask(activeToken = token, activeQuestion = question) {
    setLoading(true);
    try {
      const auth = activeToken || await login();
      const response = await fetch('/v1/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${auth}` },
        body: JSON.stringify({ question: activeQuestion }),
      });
      setAnswer(await response.json());
    } finally {
      setLoading(false);
    }
  }

  async function compare() {
    setLoading(true);
    try {
      const personas = [
        { name: 'Dave', role: 'Acme Employee (No Salary Access)', username: 'dave' },
        { name: 'Bob', role: 'Acme HR (Salary Access)', username: 'bob' },
        { name: 'Frank', role: 'Globex Admin (Cross-Tenant)', username: 'frank' },
      ];
      const results = await Promise.all(
        personas.map(async (p) => {
          const auth = await login(p.username);
          const response = await fetch('/v1/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${auth}` },
            body: JSON.stringify({ question }),
          });
          return { ...p, result: await response.json() };
        })
      );
      setComparison(results);
    } finally {
      setLoading(false);
    }
  }

  async function loadAudit() {
    try {
      const auth = token || await login('alice');
      const response = await fetch('/v1/audit/logs', {
        headers: { Authorization: `Bearer ${auth}` },
      });
      if (response.ok) {
        setLogs(await response.json());
        setToken(auth);
      }
    } catch (e) {
      console.error(e);
    }
  }

  async function verifyChain() {
    try {
      const auth = token || await login('alice');
      const response = await fetch('/v1/audit/verify', {
        headers: { Authorization: `Bearer ${auth}` },
      });
      const data = await response.json();
      setVerifyStatus(data);
    } catch (e) {
      setVerifyStatus({ valid: false, error: String(e) });
    }
  }

  async function loadWhoSaw() {
    try {
      const auth = token || await login('alice');
      const response = await fetch(`/v1/audit/who-saw/${encodeURIComponent(docId)}`, {
        headers: { Authorization: `Bearer ${auth}` },
      });
      if (response.ok) {
        setWhoSaw(await response.json());
      }
    } catch (e) {
      console.error(e);
    }
  }

  const visibleLogs = logs.filter(
    (log) =>
      !filter ||
      `${log.action} ${log.user_id} ${JSON.stringify(log.details)}`
        .toLowerCase()
        .includes(filter.toLowerCase())
  );

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">GATEKEEP / ACCESS-AWARE RAG</p>
          <h1>
            One question.<br />
            <em>Different truth.</em>
          </h1>
        </div>
        <nav>
          {[
            ['chat', 'Ask'],
            ['compare', 'Compare Roles'],
            ['audit', 'Audit Explorer'],
          ].map(([key, label]) => (
            <button
              className={view === key ? 'active' : ''}
              onClick={() => {
                setView(key);
                if (key === 'audit') {
                  loadAudit();
                  verifyChain();
                }
              }}
              key={key}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      {view === 'chat' && (
        <section className="panel">
          <label>
            Signed-in persona:
            <select
              value={user}
              onChange={(e) => {
                setUser(e.target.value);
                setToken('');
                setAnswer(null);
              }}
            >
              {SEEDED_USERS.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Question
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={3}
            />
          </label>
          <button className="primary" disabled={loading} onClick={() => ask()}>
            {loading ? 'Querying...' : 'Ask question'}
          </button>
          {answer && <Result result={answer} />}
        </section>
      )}

      {view === 'compare' && (
        <section className="panel">
          <label>
            Question
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={2}
            />
          </label>
          <button className="primary" disabled={loading} onClick={compare}>
            {loading ? 'Evaluating...' : 'Compare Roles Side-by-Side'}
          </button>
          <div className="comparison">
            {comparison.map((item) => (
              <article key={item.username}>
                <div className="role-header">
                  <strong>{item.name}</strong>
                  <span className="role-badge">{item.role}</span>
                </div>
                <Result result={item.result} />
              </article>
            ))}
          </div>
        </section>
      )}

      {view === 'audit' && (
        <section className="panel">
          <div className="audit-header">
            <h3>Audit Log & Cryptographic Verification</h3>
            {verifyStatus && (
              <div className={`chain-badge ${verifyStatus.valid ? 'chain-valid' : 'chain-invalid'}`}>
                {verifyStatus.valid
                  ? `✓ Audit Chain Cryptographically Verified (${verifyStatus.records_verified ?? 'All'} records)`
                  : `✗ Chain Tampering Detected: ${verifyStatus.error || 'Invalid hash chain'}`}
              </div>
            )}
          </div>
          <div className="toolbar">
            <input
              placeholder="Filter by action, user ID, or chunk details..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <button onClick={() => { loadAudit(); verifyChain(); }}>
              Refresh & Re-verify
            </button>
          </div>
          <div className="audit-list">
            {visibleLogs.map((log) => (
              <article key={log.id}>
                <strong>{log.action}</strong>
                <span>{log.user_id}</span>
                <small>{log.timestamp}</small>
                <code>{JSON.stringify(log.details)}</code>
              </article>
            ))}
          </div>
          <div className="who">
            <h4>Who saw this document?</h4>
            <div className="who-input">
              <input
                placeholder="Document ID (e.g. salary-acme-doc)"
                value={docId}
                onChange={(e) => setDocId(e.target.value)}
              />
              <button onClick={loadWhoSaw}>Lookup Access History</button>
            </div>
            <div className="who-results">
              {whoSaw.length === 0 ? (
                <p className="empty-hint">No queries have accessed this document yet.</p>
              ) : (
                whoSaw.map((item) => (
                  <p key={item.audit_id}>
                    <strong>{item.user_id}</strong> accessed at {item.timestamp} (audit ID: {item.audit_id.slice(0, 8)}...)
                  </p>
                ))
              )}
            </div>
          </div>
        </section>
      )}
    </main>
  );
}

function Result({ result }) {
  const citations = result?.citations || [];
  return (
    <div className="result">
      <p className="answer-text">{result?.answer || 'No response returned.'}</p>
      <div className="citations">
        <strong>Verified Citations: </strong>
        {citations.length === 0 ? (
          <span className="no-citations">None (standard no-results response)</span>
        ) : (
          citations.map((citation) => (
            <span key={citation.chunk_id} className="citation-tag">
              [{citation.chunk_id}] (doc: {citation.doc_id})
            </span>
          ))
        )}
      </div>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
