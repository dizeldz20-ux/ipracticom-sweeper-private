import React, { useState, useEffect, useRef } from 'react';
import { Machine, Alert } from '../types';
import { Server, PhoneCall, AlertTriangle, CheckCircle2, XCircle, Cpu, HardDrive } from 'lucide-react';
import { ResponsiveContainer, LineChart, Line, YAxis } from 'recharts';

import { MetricsChart } from './MetricsChart';
import { CpuSparklineWidget } from './CpuSparklineWidget';
import { HeatmapWidget } from './HeatmapWidget';
import { LogStreamWidget } from './LogStreamWidget';

const criticalTrendData = [
  { value: 1 }, { value: 0 }, { value: 3 }, { value: 1 }, { value: 4 }, { value: 2 }, { value: 5 }
];

interface DashboardProps {
  machines: Machine[];
  alerts: Alert[];
  onUpdateAlertStatus?: (id: string, status: Alert['status']) => void;
  onSnoozeAlert?: (id: string, durationMinutes: number) => void;
}

export function Dashboard({ machines, alerts, onUpdateAlertStatus, onSnoozeAlert }: DashboardProps) {
  const [activeTab, setActiveTab] = useState<'all' | 'network' | 'performance' | 'security' | 'system'>('all');
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 10000);
    return () => clearInterval(timer);
  }, []);

  const isSnoozed = (a: Alert) => a.snoozedUntil && new Date(a.snoozedUntil) > now;
  const visibleAlerts = alerts.filter(a => a.status !== 'resolved' && !isSnoozed(a));

  const activeAlerts = visibleAlerts.filter(a => activeTab === 'all' || a.eventType === activeTab);
  const criticalCount = visibleAlerts.filter(a => a.level === 'critical').length;
  const warningCount = visibleAlerts.filter(a => a.level === 'warning').length;
  const infoCount = visibleAlerts.filter(a => a.level === 'info').length;

  const [pulseCritical, setPulseCritical] = useState(false);
  const prevCriticalCount = useRef(criticalCount);

  useEffect(() => {
    if (criticalCount > prevCriticalCount.current) {
      setPulseCritical(true);
      const timer = setTimeout(() => setPulseCritical(false), 3000);
      return () => clearTimeout(timer);
    }
    prevCriticalCount.current = criticalCount;
  }, [criticalCount]);
  
  return (
    <div className="p-8 flex flex-col gap-6 animate-in fade-in duration-500" dir="rtl">
      
      <header className="flex justify-between items-end">
        <div>
          <h2 className="text-2xl font-bold text-white">מבט על המערכת</h2>
          <p className="text-slate-400">מעקב אחר {machines.length} שרתים ומרכזיות</p>
        </div>
        <div className="flex gap-4">
          <div className="bg-slate-900 px-4 py-2 rounded-lg border border-slate-800 text-sm">
            <span className="text-slate-500">מכונות פעילות:</span>
            <span className="text-emerald-400 mr-2" dir="ltr">{machines.filter(m => m.status === 'online').length}/{machines.length}</span>
          </div>
          <div className="bg-slate-900 px-4 py-2 rounded-lg border border-slate-800 text-sm">
            <span className="text-slate-500">התראות פעילות:</span>
            <span className="text-white mr-2">{visibleAlerts.length}</span>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 flex-1">
        {/* Overview Stats Bento Grid */}
        <div className="lg:col-span-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
          <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6 flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-400 font-medium">סה"כ מכונות</p>
              <h3 className="text-3xl font-bold text-slate-100 mt-2">{machines.length}</h3>
            </div>
            <div className="p-3 bg-indigo-500/10 rounded-lg">
              <Server className="w-6 h-6 text-indigo-400" />
            </div>
          </div>
          
          <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6 flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-400 font-medium">מרכזיות (PBX)</p>
              <h3 className="text-3xl font-bold text-slate-100 mt-2">
                {machines.filter(m => m.type === 'pbx').length}
              </h3>
            </div>
            <div className="p-3 bg-purple-500/10 rounded-lg">
              <PhoneCall className="w-6 h-6 text-purple-400" />
            </div>
          </div>

          <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6 flex flex-col justify-center">
            <div className="flex justify-between items-center mb-3">
              <p className="text-sm text-slate-400 font-medium">סיכום התראות פעילות</p>
              <AlertTriangle className="w-5 h-5 text-slate-500" />
            </div>
            <div className="flex gap-2 mb-3">
              <div className={`flex flex-col items-center justify-center p-2 bg-rose-500/10 rounded-xl flex-1 border border-rose-500/20 ${pulseCritical ? 'animate-pulse ring-2 ring-rose-500/50 scale-105 transition-all shadow-[0_0_15px_rgba(225,29,72,0.5)]' : 'transition-all'}`}>
                <span className="text-xl font-bold text-rose-400">{criticalCount}</span>
                <span className="text-[10px] font-medium text-rose-400/80 mt-1 uppercase">קריטי</span>
              </div>
              <div className="flex flex-col items-center justify-center p-2 bg-amber-500/10 rounded-xl flex-1 border border-amber-500/20">
                <span className="text-xl font-bold text-amber-400">{warningCount}</span>
                <span className="text-[10px] font-medium text-amber-400/80 mt-1 uppercase">אזהרה</span>
              </div>
              <div className="flex flex-col items-center justify-center p-2 bg-emerald-500/10 rounded-xl flex-1 border border-emerald-500/20">
                <span className="text-xl font-bold text-emerald-400">{infoCount}</span>
                <span className="text-[10px] font-medium text-emerald-400/80 mt-1 uppercase">מידע</span>
              </div>
            </div>
            
            <div className="h-6 w-full opacity-70">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={criticalTrendData}>
                  <YAxis domain={['dataMin', 'dataMax']} hide />
                  <Line 
                    type="monotone" 
                    dataKey="value" 
                    stroke="#f43f5e" 
                    strokeWidth={2} 
                    dot={false} 
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <CpuSparklineWidget machines={machines} />
        </div>

        {/* Metrics Chart and Heatmap */}
        <div className="lg:col-span-2">
          <MetricsChart alerts={alerts} />
        </div>
        <div className="lg:col-span-2">
          <HeatmapWidget />
        </div>

        {/* Live Alerts Feed (Replaces real-time logs layout) */}
        <div className="lg:col-span-3 bg-slate-900 rounded-3xl border border-slate-800 p-6 flex flex-col overflow-hidden h-[400px]">
          <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-4">
            <h3 className="text-lg font-semibold text-white">יומן אירועים חי (Real-time Logs)</h3>
            <div className="flex items-center gap-2">
              <div className="flex bg-slate-800/50 p-1 rounded-xl">
                {(['all', 'network', 'performance', 'security', 'system'] as const).map(tab => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                      activeTab === tab 
                        ? 'bg-slate-700 text-white shadow-sm' 
                        : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
                    }`}
                  >
                    {tab === 'all' ? 'הכל' : tab === 'network' ? 'רשת' : tab === 'performance' ? 'ביצועים' : tab === 'security' ? 'אבטחה' : 'מערכת'}
                  </button>
                ))}
              </div>
              <span className="text-xs px-2 py-1 bg-rose-500/10 text-rose-500 border border-rose-500/20 rounded-md">סריקה פעילה</span>
            </div>
          </div>
          <div className="flex-1 font-mono text-sm space-y-3 overflow-y-auto">
             {activeAlerts.length === 0 ? (
               <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-3">
                 <CheckCircle2 className="w-8 h-8 opacity-50" />
                 <p className="text-sm font-sans">אין התראות פעילות</p>
               </div>
            ) : (
              activeAlerts.map(alert => (
                <div key={alert.id} className={`flex flex-col md:flex-row md:items-center justify-between gap-4 p-3 rounded bg-slate-800/30 border-r-2 ${
                  alert.level === 'critical' ? 'border-rose-500' :
                  alert.level === 'warning' ? 'border-amber-500' :
                  'border-emerald-500'
                }`}>
                  <div className="flex flex-col md:flex-row md:items-center gap-3 md:gap-4 flex-1">
                      <div className="flex gap-2 items-center min-w-max">
                        <span className="text-slate-500 text-xs md:text-sm">[{new Date(alert.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'})}]</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-sm font-bold uppercase tracking-wider ${
                          alert.priority === 'urgent' ? 'bg-red-600 text-white' :
                          alert.priority === 'high' ? 'bg-orange-500 text-white' :
                          alert.priority === 'medium' ? 'bg-yellow-500/80 text-white' :
                          'bg-slate-600 text-white'
                        }`}>{alert.priority}</span>
                        <span className={`${
                          alert.level === 'critical' ? 'text-rose-500' :
                          alert.level === 'warning' ? 'text-amber-400' :
                          'text-emerald-400'
                        }`}>[{alert.level.toUpperCase()}]</span>
                      </div>
                    <span className="text-slate-300 font-sans text-sm"><span className="font-semibold text-slate-200">{alert.machineName}:</span> {alert.message}</span>
                  </div>
                  <div className="flex items-center gap-2 font-sans self-end md:self-center shrink-0 mt-2 md:mt-0">
                    <div className="relative group">
                      <button 
                        className="text-xs px-2.5 py-1.5 bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200 rounded-lg transition-colors border border-slate-700 whitespace-nowrap"
                      >
                        השהה
                      </button>
                      <div className="absolute right-0 bottom-full mb-2 w-32 rounded-xl bg-slate-800 border border-slate-700 shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 overflow-hidden">
                        <button onClick={() => onSnoozeAlert?.(alert.id, 15)} className="w-full text-right px-3 py-2 text-xs text-slate-300 hover:bg-slate-700 transition-colors border-b border-slate-700/50">15 דקות</button>
                        <button onClick={() => onSnoozeAlert?.(alert.id, 60)} className="w-full text-right px-3 py-2 text-xs text-slate-300 hover:bg-slate-700 transition-colors border-b border-slate-700/50">שעה 1</button>
                        <button onClick={() => onSnoozeAlert?.(alert.id, 24 * 60)} className="w-full text-right px-3 py-2 text-xs text-slate-300 hover:bg-slate-700 transition-colors">24 שעות</button>
                      </div>
                    </div>
                    {alert.status === 'unread' && (
                      <button 
                        onClick={() => onUpdateAlertStatus?.(alert.id, 'in-progress')}
                        className="text-xs px-2.5 py-1.5 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 rounded-lg transition-colors border border-amber-500/20 whitespace-nowrap"
                      >
                        סמן בטיפול
                      </button>
                    )}
                    <button 
                      onClick={() => onUpdateAlertStatus?.(alert.id, 'resolved')}
                      className="text-xs px-2.5 py-1.5 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 rounded-lg transition-colors border border-emerald-500/20 whitespace-nowrap"
                    >
                      סמן כנפתר
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Machine Status List */}
        <div className="lg:col-span-1 bg-slate-900 rounded-3xl border border-slate-800 p-6 flex flex-col h-[400px] overflow-hidden">
          <h3 className="text-lg font-semibold text-white mb-6">סטטוס מכונות</h3>
          <div className="space-y-4 overflow-y-auto pr-2">
            {machines.map(machine => (
              <div key={machine.id} className={`flex items-center justify-between p-3 bg-slate-800/40 rounded-2xl border ${machine.status === 'warning' ? 'border-amber-500/30' : machine.status === 'offline' ? 'border-rose-500/30' : 'border-transparent'}`}>
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${
                    machine.status === 'online' ? 'bg-emerald-500' :
                    machine.status === 'warning' ? 'bg-amber-500 animate-pulse' :
                    'bg-rose-500'
                  }`}></div>
                  <span className="text-sm">{machine.name}</span>
                </div>
                <span className={`text-xs font-mono ${
                  machine.status === 'warning' ? 'text-amber-500' :
                  machine.status === 'offline' ? 'text-rose-500' :
                  'text-slate-500'
                }`}>
                  {machine.status === 'online' ? machine.ip : machine.status === 'warning' ? 'LATENCY' : 'OFFLINE'}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Real-time Log Streaming Window */}
        <div className="lg:col-span-4">
          <LogStreamWidget />
        </div>

      </div>
    </div>
  );
}
