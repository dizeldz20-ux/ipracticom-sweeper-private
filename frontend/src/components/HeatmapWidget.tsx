import {useMemo} from 'react';
import {Activity} from 'lucide-react';
import {getHeatmap} from '../services/endpoints';
import {usePolling} from '../hooks/usePolling';

const getHeatmapColor = (value: number) => {
  if (value === 0) return 'bg-slate-800/50';
  if (value < 10) return 'bg-indigo-500/20';
  if (value < 25) return 'bg-indigo-500/40';
  if (value < 40) return 'bg-indigo-500/70';
  return 'bg-indigo-500';
};

export function HeatmapWidget() {
  const {data} = usePolling((signal) => getHeatmap(signal), 30000);
  const buckets = useMemo(() => {
    const lastRow = data?.grid?.[data.grid.length - 1] || [];
    return Array.from({length: 24}).map((_, hour) => ({
      hour,
      value: Number(lastRow[hour] || 0),
    }));
  }, [data]);

  return (
    <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6 flex flex-col justify-between">
      <div className="flex justify-between items-start mb-4">
        <div>
          <h3 className="text-sm font-medium text-slate-400">צפיפות אירועים ב-24 השעות האחרונות</h3>
          <p className="text-xs text-slate-500 mt-1">מקור: /v6/metrics/events_heatmap</p>
        </div>
        <div className="p-3 bg-indigo-500/10 rounded-lg">
          <Activity className="w-5 h-5 text-indigo-400" />
        </div>
      </div>

      <div className="flex-1 flex flex-col justify-end mt-4">
        <div className="grid grid-cols-12 gap-1 h-12 md:[grid-template-columns:repeat(24,minmax(0,1fr))]" dir="ltr">
          {buckets.map((bucket) => (
            <div key={bucket.hour} className="flex flex-col items-center group relative h-full">
              <div
                className={`w-full h-full rounded-sm ${getHeatmapColor(bucket.value)} transition-colors cursor-pointer group-hover:ring-1 group-hover:ring-indigo-400`}
              />
              <div className="absolute bottom-full mb-2 hidden group-hover:flex flex-col items-center z-10 w-max">
                <span className="relative z-10 p-2 text-xs leading-none text-white whitespace-no-wrap bg-slate-800 shadow-lg rounded-md border border-slate-700">
                  {`${bucket.hour.toString().padStart(2, '0')}:00 — ${bucket.value} אירועים`}
                </span>
                <div className="w-3 h-3 -mt-2 rotate-45 bg-slate-800 border-b border-r border-slate-700" />
              </div>
              <span className="text-[10px] text-slate-500 mt-2 hidden md:block">
                {bucket.hour % 4 === 0 ? bucket.hour.toString().padStart(2, '0') : ''}
              </span>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between mt-4 text-[10px] text-slate-500 border-t border-slate-800/50 pt-2">
          <span>00:00</span>
          <div className="flex items-center gap-1 mx-4" dir="ltr">
            <span className="mr-2 text-slate-400">נמוך</span>
            <div className="w-3 h-3 rounded-sm bg-slate-800/50" />
            <div className="w-3 h-3 rounded-sm bg-indigo-500/20" />
            <div className="w-3 h-3 rounded-sm bg-indigo-500/40" />
            <div className="w-3 h-3 rounded-sm bg-indigo-500/70" />
            <div className="w-3 h-3 rounded-sm bg-indigo-500" />
            <span className="ml-2 text-slate-400">גבוה</span>
          </div>
          <span>23:00</span>
        </div>
      </div>
    </div>
  );
}
