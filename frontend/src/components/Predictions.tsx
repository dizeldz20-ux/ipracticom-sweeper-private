import {useMemo} from 'react';
import {BrainCircuit, RefreshCw} from 'lucide-react';
import {getPredictions} from '../services/endpoints';
import {usePolling} from '../hooks/usePolling';

function eta(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return 'לא נצפה';
  if (seconds < 3600) return `${Math.round(seconds / 60)} דק׳`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} שעות`;
  return `${Math.round(seconds / 86400)} ימים`;
}

export function Predictions() {
  const {data, loading, refetch} = usePolling((signal) => getPredictions(signal), 30000);
  const predictions = useMemo(() => data?.predictions || [], [data]);

  return (
    <div className="p-8 flex flex-col gap-6 animate-in fade-in duration-500" dir="rtl">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">תחזיות</h2>
          <p className="text-slate-400">תחזיות חציית ספים ממאגר סדרות-הזמן של הסוכן.</p>
        </div>
        <button
          onClick={refetch}
          className="p-2 rounded-xl bg-slate-800 text-slate-300 border border-slate-700 hover:bg-slate-700"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {loading ? (
          <div className="text-slate-500">טוען תחזיות...</div>
        ) : predictions.length === 0 ? (
          <div className="md:col-span-2 xl:col-span-3 bg-slate-900 rounded-3xl border border-slate-800 p-8 text-slate-500">
            {data?.note || 'אין נתוני תחזית עדיין.'}
          </div>
        ) : (
          predictions.map((p, idx) => (
            <div key={`${p.metric || 'metric'}-${idx}`} className="bg-slate-900 rounded-3xl border border-slate-800 p-6">
              <div className="flex items-center justify-between mb-5">
                <div className="p-3 bg-indigo-500/10 rounded-lg">
                  <BrainCircuit className="w-5 h-5 text-indigo-400" />
                </div>
                <span className={`text-xs px-2 py-1 rounded border ${
                  p.will_cross ? 'text-rose-300 bg-rose-500/10 border-rose-500/20' : 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20'
                }`}>
                  {p.will_cross ? 'סיכון' : 'יציב'}
                </span>
              </div>
              <h3 className="text-lg font-semibold text-white" dir="ltr">{p.metric || 'metric'}</h3>
              <div className="mt-4 space-y-2 text-sm text-slate-400">
                <div className="flex justify-between"><span>נוכחי</span><span dir="ltr">{String(p.current ?? '-')}</span></div>
                <div className="flex justify-between"><span>סף</span><span dir="ltr">{String(p.threshold ?? '-')}</span></div>
                <div className="flex justify-between"><span>זמן משוער</span><span dir="ltr">{eta(p.eta_seconds)}</span></div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
