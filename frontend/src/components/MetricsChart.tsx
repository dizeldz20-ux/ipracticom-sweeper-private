import {useMemo} from 'react';
import {Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis} from 'recharts';
import type {Alert} from '../types';

interface MetricsChartProps {
  alerts: Alert[];
}

export function MetricsChart({alerts}: MetricsChartProps) {
  const data = useMemo(() => {
    const now = new Date();
    return Array.from({length: 7}).map((_, i) => {
      const start = new Date(now);
      start.setHours(now.getHours() - (6 - i) * 4, 0, 0, 0);
      const end = new Date(start);
      end.setHours(start.getHours() + 4);
      const bucketAlerts = alerts.filter((alert) => {
        const t = Date.parse(alert.timestamp);
        return !Number.isNaN(t) && t >= start.getTime() && t < end.getTime();
      });
      return {
        time: start.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}),
        events: bucketAlerts.length,
        alerts: bucketAlerts.filter((a) => a.level !== 'info').length,
      };
    });
  }, [alerts]);

  return (
    <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6 flex flex-col w-full h-[350px]">
      <h3 className="text-lg font-semibold text-white mb-6">מגמת אירועים ב-24 השעות האחרונות</h3>
      <div className="flex-1 w-full h-full" dir="ltr">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{top: 10, right: 30, left: 0, bottom: 0}}>
            <defs>
              <linearGradient id="colorEvents" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="colorAlerts" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
            <XAxis dataKey="time" stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} />
            <YAxis stroke="#94a3b8" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
            <Tooltip
              contentStyle={{backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '0.75rem', color: '#f8fafc'}}
              itemStyle={{color: '#f8fafc'}}
            />
            <Area type="monotone" dataKey="events" name="אירועים" stroke="#6366f1" strokeWidth={2} fillOpacity={1} fill="url(#colorEvents)" />
            <Area type="monotone" dataKey="alerts" name="התראות" stroke="#f43f5e" strokeWidth={2} fillOpacity={1} fill="url(#colorAlerts)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
