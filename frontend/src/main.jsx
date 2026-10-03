import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

function App() {
  const [user, setUser] = useState('bob');
  const [token, setToken] = useState('');
  const [question, setQuestion] = useState('salary band engineers');
  const [answer, setAnswer] = useState(null);
  const [view, setView] = useState('chat');
  const [comparison, setComparison] = useState([]);
  const [logs, setLogs] = useState([]);
  const [filter, setFilter] = useState('');
  const [docId, setDocId] = useState('');
  const [whoSaw, setWhoSaw] = useState([]);

  async function login(username = user) {
    const response = await fetch('/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password: username }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Login failed');
    setToken(data.access_token);
    return data.access_token;
  }

  async function ask(activeToken = token, activeQuestion = question) {
    const auth = activeToken || await login();
    const response = await fetch('/v1/query', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${auth}` }, body: JSON.stringify({ question: activeQuestion }) });
    setAnswer(await response.json());
  }

  async function compare() {
    const results = await Promise.all(['dave', 'bob', 'frank'].map(async (name) => ({ name, result: await fetch('/v1/query', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${await login(name)}` }, body: JSON.stringify({ question }) }).then(response => response.json()) })));
    setComparison(results);
  }

  async function loadAudit() {
    const auth = token || await login('alice');
    const response = await fetch('/v1/audit/logs', { headers: { Authorization: `Bearer ${auth}` } });
    setLogs(await response.json());
    setToken(auth);
  }

  async function loadWhoSaw() {
    const auth = token || await login('alice');
    const response = await fetch(`/v1/audit/who-saw/${encodeURIComponent(docId)}`, { headers: { Authorization: `Bearer ${auth}` } });
    setWhoSaw(await response.json());
  }
  const visibleLogs = logs.filter(log => !filter || `${log.action} ${log.user_id} ${JSON.stringify(log.details)}`.toLowerCase().includes(filter.toLowerCase()));
  return <main>
    <header><div><p className="eyebrow">GATEKEEP / ACCESS-AWARE RAG</p><h1>One question.<br/><em>Different truth.</em></h1></div><nav>{[['chat','Ask'],['compare','Compare'],['audit','Audit']].map(([key,label]) => <button className={view === key ? 'active' : ''} onClick={() => { setView(key); if (key === 'audit') loadAudit(); }} key={key}>{label}</button>)}</nav></header>
    {view === 'chat' && <section className="panel"><label>Signed-in user<select value={user} onChange={event => { setUser(event.target.value); setToken(''); }}><option>bob</option><option>dave</option><option>frank</option></select></label><label>Question<textarea value={question} onChange={event => setQuestion(event.target.value)} /></label><button className="primary" onClick={() => ask()}>Ask question</button>{answer && <Result result={answer} />}</section>}
    {view === 'compare' && <section className="panel"><label>Question<textarea value={question} onChange={event => setQuestion(event.target.value)} /></label><button className="primary" onClick={compare}>Compare roles</button><div className="comparison">{comparison.map(item => <article key={item.name}><span className="role">{item.name}</span><Result result={item.result} /></article>)}</div></section>}
    {view === 'audit' && <section className="panel"><div className="toolbar"><input placeholder="Filter action, user, document" value={filter} onChange={event => setFilter(event.target.value)} /><button onClick={loadAudit}>Refresh</button></div><div className="audit-list">{visibleLogs.map(log => <article key={log.id}><strong>{log.action}</strong><span>{log.user_id}</span><small>{log.timestamp}</small><code>{JSON.stringify(log.details)}</code></article>)}</div><div className="who"><label>Who saw document<input value={docId} onChange={event => setDocId(event.target.value)} /></label><button onClick={loadWhoSaw}>Lookup</button>{whoSaw.map(item => <p key={item.audit_id}>{item.user_id} · {item.timestamp}</p>)}</div></section>}
  </main>;
}

function Result({ result }) { return <div className="result"><p>{result?.answer}</p><div className="citations">{(result?.citations || []).map(citation => <span key={citation.chunk_id}>[{citation.chunk_id}]</span>)}</div></div>; }
createRoot(document.getElementById('root')).render(<App/>);
