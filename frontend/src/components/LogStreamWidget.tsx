import {useEffect, useRef, useState} from 'react';
import {Pause, Play, Terminal} from 'lucide-react';
import {getV6Logs} from '../services/endpoints';
import {usePolling} from '../hooks/usePolling';

export function LogStreamWidget() {
  const [isPaused, setIsPaused] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const {data} = usePolling((signal) => getV6Logs(signal), isPaused ? 600000 : 5000);
  const lines = data?.lines || [];

  useEffect(() => {
    if (!isPaused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [lines, isPaused]);

  return (
    <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6 flex flex-col h-[300px] overflow-hidden">
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center gap-2">
          <Terminal className="w-5 h-5 text-slate-400" />
          <h3 className="text-sm font-semibold text-white">יומני מערכת</h3>
          {data?.log ? <span className="text-xs text-slate-500" dir="ltr">{data.log}</span> : null}
        </div>
        <div className="flex items-center gap-3">
          {isPaused && <span className="text-xs text-amber-500 animate-pulse">מושהה</span>}
          <button
            onClick={() => setIsPaused(!isPaused)}
            className={`px-3 py-1.5 rounded-lg flex items-center gap-2 text-xs font-medium transition-colors ${
              isPaused ? 'bg-amber-500/10 text-amber-500 hover:bg-amber-500/20 border border-amber-500/20' : 'bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20 border border-emerald-500/20'
            }`}
          >
            {isPaused ? (
              <>
                <Play className="w-3 h-3" />
                המשך
              </>
            ) : (
              <>
                <Pause className="w-3 h-3" />
                השהה
              </>
            )}
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto font-mono text-xs bg-slate-950 p-4 rounded-xl border border-slate-800 space-y-2 scroll-smooth"
        dir="ltr"
      >
        {lines.length ? (
          lines.map((line, idx) => (
            <div key={`${idx}-${line}`} className="text-slate-400 hover:text-slate-300 transition-colors break-all">
              {line}
            </div>
          ))
        ) : (
          <div className="text-slate-600">אין שורות יומן עדיין</div>
        )}
      </div>
    </div>
  );
}
