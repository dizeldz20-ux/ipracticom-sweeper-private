import {useMemo} from 'react';
import {Activity, TrendingUp} from 'lucide-react';
import {Line, LineChart, ResponsiveContainer, YAxis} from 'recharts';
import type {Machine} from '../types';

interface CpuSparklineWidgetProps {
  machines: Machine[];
}

export function CpuSparklineWidget({machines}: CpuSparklineWidgetProps) {
  const cpu = machines.length
    ? Math.round(machines.reduce((sum, m) => sum + (m.cpuUsage || 0), 0) / machines.length)
    : 0;
  const data = useMemo(
    () => Array.from({length: 10}).map((_, i) => ({value: Math.max(0, Math.min(100, cpu + i - 5))})),
    [cpu],
  );

  return (
    <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6 flex flex-col justify-between">
      <div className="flex justify-between items-start mb-4">
        <div>
          <h3 className="text-sm font-medium text-slate-400">עומס מעבד ממוצע</h3>
          <div className="flex items-center gap-2 mt-2">
            <span className="text-3xl font-bold text-white">{cpu}%</span>
            <span className={`flex items-center text-xs font-medium px-2 py-0.5 rounded-full border ${
              cpu >= 85
                ? 'text-rose-400 bg-rose-500/10 border-rose-500/20'
                : 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
            }`}>
              <TrendingUp className="w-3 h-3 ml-1" />
              {cpu >= 85 ? 'גבוה' : 'יציב'}
            </span>
          </div>
        </div>
        <div className="p-3 bg-indigo-500/10 rounded-lg">
          <Activity className="w-6 h-6 text-indigo-400" />
        </div>
      </div>

      <div className="h-12 w-full mt-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <YAxis domain={[0, 100]} hide />
            <Line
              type="monotone"
              dataKey="value"
              stroke={cpu >= 85 ? '#f43f5e' : '#10b981'}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-4 pt-4 border-t border-slate-800/50 flex items-center justify-between text-xs">
        <span className="text-slate-400">מקור:</span>
        <span className="text-slate-300 bg-slate-800 px-2 py-1 rounded">/api/fleet + /api/snapshot</span>
      </div>
    </div>
  );
}
