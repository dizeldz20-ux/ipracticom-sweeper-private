import {useMemo} from 'react';
import {Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';
import {format} from 'date-fns';
import {getUptime30d} from '../services/endpoints';
import {usePolling} from '../hooks/usePolling';

export function UptimeChartWidget() {
  const {data} = usePolling((signal) => getUptime30d(signal), 60000);
  const points = useMemo(
    () =>
      (data?.points || []).map((p) => ({
        date: format(new Date(p.date), 'dd/MM'),
        uptime: Math.round((p.ratio || 0) * 10000) / 100,
      })),
    [data],
  );

  return (
    <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6 flex flex-col w-full h-[300px]">
      <h3 className="text-lg font-semibold text-white mb-6">אומדן זמן פעילות ב-30 הימים האחרונים</h3>
      <div className="flex-1 w-full h-full" dir="ltr">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points} margin={{top: 10, right: 30, left: 0, bottom: 0}}>
            <defs>
              <linearGradient id="colorUptime" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis dataKey="date" stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} />
            <YAxis stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} domain={[90, 100]} tickFormatter={(val) => `${val}%`} />
            <Tooltip
              contentStyle={{backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '0.75rem', color: '#f8fafc'}}
              itemStyle={{color: '#10b981'}}
              formatter={(value: number) => [`${value.toFixed(2)}%`, 'זמן פעילות']}
            />
            <Area type="monotone" dataKey="uptime" stroke="#10b981" strokeWidth={2} fillOpacity={1} fill="url(#colorUptime)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
