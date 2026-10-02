import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

function App() {
  const [user, setUser] = useState('bob');
  const [answer, setAnswer] = useState('');
  async function ask() {
    const login = await fetch('/v1/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:user,password:user})});
    const {access_token} = await login.json();
    const result = await fetch('/v1/query', {method:'POST', headers:{'Content-Type':'application/json',Authorization:`Bearer ${access_token}`}, body:JSON.stringify({question:'salary band engineers'})});
    setAnswer(JSON.stringify(await result.json(), null, 2));
  }
  return <main><p className="eyebrow">GATEKEEP / ACCESS-AWARE RAG</p><h1>One question.<br/><em>Different truth.</em></h1><label>User<select value={user} onChange={event=>setUser(event.target.value)}><option>bob</option><option>dave</option><option>frank</option></select></label><button onClick={ask}>Ask salary question</button><pre>{answer || 'Choose a role to inspect its permitted context.'}</pre></main>;
}
createRoot(document.getElementById('root')).render(<App/>);
