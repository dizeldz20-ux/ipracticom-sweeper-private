import {useEffect, useRef, useState} from 'react';
import {BotMessageSquare, Send} from 'lucide-react';

interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

function wsUrl() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws`;
}

function newSessionId() {
  const c = (window.crypto as Crypto | undefined);
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  return `web-${Math.random().toString(36).slice(2)}`;
}

export function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {role: 'system', content: 'מחובר לצ׳אט של הסוכן.'},
  ]);
  const [draft, setDraft] = useState('');
  const [status, setStatus] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const socket = useRef<WebSocket | null>(null);
  const sessionId = useRef<string>(newSessionId());

  useEffect(() => {
    const ws = new WebSocket(wsUrl());
    socket.current = ws;
    ws.onopen = () => setStatus('open');
    ws.onclose = () => setStatus('closed');
    ws.onerror = () => setStatus('closed');
    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.assistant?.content) {
          setMessages((prev) => [...prev, {role: 'assistant', content: payload.assistant.content}]);
        } else if (payload.error) {
          setMessages((prev) => [...prev, {role: 'system', content: payload.error}]);
        }
      } catch {
        setMessages((prev) => [...prev, {role: 'assistant', content: String(event.data)}]);
      }
    };
    return () => ws.close();
  }, []);

  const send = () => {
    const content = draft.trim();
    if (!content || socket.current?.readyState !== WebSocket.OPEN) return;
    setMessages((prev) => [...prev, {role: 'user', content}]);
    // The backend /ws handler expects {session_id, content}.
    socket.current.send(JSON.stringify({session_id: sessionId.current, content}));
    setDraft('');
  };

  const statusLabel =
    status === 'open' ? 'מחובר' : status === 'connecting' ? 'מתחבר' : 'מנותק';

  return (
    <div className="p-8 flex flex-col gap-6 animate-in fade-in duration-500" dir="rtl">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">עוזר AI</h2>
          <p className="text-slate-400">צ׳אט חי מול הסוכן דרך WebSocket באותו מקור.</p>
        </div>
        <span className={`text-xs px-3 py-1 rounded-full border ${
          status === 'open' ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20' : 'text-amber-300 bg-amber-500/10 border-amber-500/20'
        }`}>
          {statusLabel}
        </span>
      </header>

      <div className="bg-slate-900 rounded-3xl border border-slate-800 flex flex-col h-[70vh] min-h-[420px] overflow-hidden">
        <div className="flex-1 min-h-0 p-6 space-y-4 overflow-y-auto">
          {messages.map((message, idx) => (
            <div
              key={idx}
              className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm ${
                message.role === 'user'
                  ? 'ms-auto bg-indigo-600 text-white'
                  : message.role === 'assistant'
                    ? 'me-auto bg-slate-800 text-slate-100 border border-slate-700'
                    : 'mx-auto bg-slate-950 text-slate-500 border border-slate-800'
              }`}
            >
              {message.role === 'assistant' ? <BotMessageSquare className="inline w-4 h-4 ml-2 text-indigo-400" /> : null}
              {message.content}
            </div>
          ))}
        </div>
        <div className="p-4 border-t border-slate-800 flex gap-3">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') send();
            }}
            className="flex-1 bg-slate-950 border border-slate-800 rounded-xl py-3 px-4 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
            placeholder="שאל את הסוכן..."
          />
          <button
            onClick={send}
            disabled={status !== 'open'}
            className="px-4 py-3 rounded-xl bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 disabled:hover:bg-indigo-600"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
