import React, { useState, useEffect } from 'react';
import { Machine } from '../types';
import { Server, Activity, Clock, Wrench, ChevronDown, Zap, RefreshCw, Terminal, Power } from 'lucide-react';
import { UptimeChartWidget } from './UptimeChartWidget';
import type {MachineAction} from '../services/endpoints';

interface MachineListProps {
  machines: Machine[];
  onToggleMaintenance?: (id: string, durationMinutes?: number) => void;
  onMachineAction?: (id: string, action: MachineAction) => void;
}

export function MachineList({ machines, onToggleMaintenance, onMachineAction }: MachineListProps) {
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 10000);
    return () => clearInterval(timer);
  }, []);
  return (
    <div className="p-8 flex flex-col gap-6 animate-in fade-in duration-500" dir="rtl">
      <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h2 className="text-2xl font-bold text-white">מכונות מנוטרות</h2>
          <p className="text-slate-400">רשימה בזמן אמת של כל השרתים והמרכזיות</p>
        </div>
      </header>

      <UptimeChartWidget />

      <div className="bg-slate-900 rounded-3xl border border-slate-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-right border-collapse">
            <thead>
              <tr className="border-b border-slate-800/50 bg-slate-800/20 text-slate-400 text-sm">
                <th className="py-4 px-6 font-medium">סטטוס</th>
                <th className="py-4 px-6 font-medium">שם מארח (Hostname)</th>
                <th className="py-4 px-6 font-medium text-left" dir="ltr">IP</th>
                <th className="py-4 px-6 font-medium text-center">עדכון אחרון</th>
                <th className="py-4 px-6 font-medium text-center min-w-[150px]">פעולות</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/30">
              {machines.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-12 text-center text-slate-500">
                    אין מכונות מנוטרות עדיין
                  </td>
                </tr>
              ) : machines.map(machine => (
                <tr key={machine.id} className={`transition-colors ${machine.maintenanceMode ? 'bg-amber-500/5 hover:bg-amber-500/10' : 'hover:bg-slate-800/40'}`}>
                  <td className="py-4 px-6">
                    <div className="flex items-center gap-2">
                      <span className={`inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium border ${
                        machine.status === 'online' ? 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20' :
                        machine.status === 'warning' ? 'text-amber-400 bg-amber-400/10 border-amber-400/20' :
                        'text-rose-400 bg-rose-400/10 border-rose-400/20'
                      }`}>
                        <div className={`w-1.5 h-1.5 rounded-full ${
                          machine.status === 'online' ? 'bg-emerald-400' :
                          machine.status === 'warning' ? 'bg-amber-400 animate-pulse' :
                          'bg-rose-400'
                        }`} />
                        {machine.status === 'online' ? 'פעיל' : machine.status === 'warning' ? 'שגיאה' : 'לא פעיל'}
                      </span>
                      {machine.maintenanceMode && (
                        <div className="flex flex-col gap-1 items-start">
                          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-500 border border-amber-500/30 uppercase tracking-wider">
                            תחזוקה
                          </span>
                          {machine.maintenanceEndTime && (
                            <span className="text-[10px] text-amber-500/70">
                              מסתיים ב: {new Date(machine.maintenanceEndTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </td>
                  <td className="py-4 px-6">
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-slate-800 rounded-lg">
                        <Server className="w-5 h-5 text-indigo-400" />
                      </div>
                      <span className="font-medium text-slate-200">{machine.name}</span>
                    </div>
                  </td>
                  <td className="py-4 px-6 text-slate-300 font-mono text-sm text-left" dir="ltr">{machine.ip}</td>
                  <td className="py-4 px-6 text-center text-slate-400 text-sm">
                    <div className="flex items-center justify-center gap-2">
                      <Clock className="w-4 h-4 text-slate-500" />
                      <span dir="ltr">{new Date(machine.lastUpdate).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                    </div>
                  </td>
                  <td className="py-4 px-6 text-center">
                    <div className="flex items-center justify-end gap-2">
                      
                      {/* Quick Actions Dropdown */}
                      <div className="relative inline-block text-right">
                        <button
                          onClick={() => setActiveMenu(activeMenu === `quick-${machine.id}` ? null : `quick-${machine.id}`)}
                          className="p-2 rounded-xl bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/20 border border-indigo-500/20 transition-all"
                          title="פעולות מהירות"
                        >
                          <Zap className="w-4 h-4" />
                        </button>
                        {activeMenu === `quick-${machine.id}` && (
                          <div className="absolute left-0 mt-2 w-48 rounded-xl bg-slate-800 border border-slate-700 shadow-xl z-50 overflow-hidden">
                            <div className="p-2 text-xs text-slate-400 font-medium border-b border-slate-700 text-right">
                              פעולות מהירות
                            </div>
                            <button
                              onClick={() => { setActiveMenu(null); onMachineAction?.(machine.id, 'agent_restart'); }}
                              className="w-full text-right px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 transition-colors flex items-center justify-between"
                            >
                              אתחול סוכן
                              <RefreshCw className="w-4 h-4 text-slate-500" />
                            </button>
                            <button
                              onClick={() => { setActiveMenu(null); onMachineAction?.(machine.id, 'ssm_connect'); }}
                              className="w-full text-right px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 transition-colors flex items-center justify-between"
                            >
                              חיבור SSM
                              <Terminal className="w-4 h-4 text-slate-500" />
                            </button>
                            <button
                              onClick={() => { setActiveMenu(null); onMachineAction?.(machine.id, 'reboot'); }}
                              className="w-full text-right px-4 py-2 text-sm text-rose-400 hover:bg-rose-500/10 transition-colors flex items-center justify-between border-t border-slate-700/50"
                            >
                              הפעלה מחדש (Reboot)
                              <Power className="w-4 h-4 text-rose-400/70" />
                            </button>
                          </div>
                        )}
                      </div>

                      {/* Maintenance Controls */}
                      <div className="relative inline-block text-right">
                        {machine.maintenanceMode ? (
                          <button 
                            onClick={() => onToggleMaintenance?.(machine.id)}
                            className="p-2 rounded-xl transition-all bg-amber-500/20 text-amber-400 border border-amber-500/30 shadow-[0_0_10px_rgba(245,158,11,0.2)]"
                            title="בטל מצב תחזוקה"
                          >
                            <Wrench className="w-4 h-4" />
                          </button>
                        ) : (
                          <div className="flex items-center gap-1">
                            <button 
                              onClick={() => onToggleMaintenance?.(machine.id)}
                              className="p-2 rounded-xl transition-all bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-700 hover:bg-slate-700"
                              title="הפעל מצב תחזוקה (ללא הגבלת זמן)"
                            >
                              <Wrench className="w-4 h-4" />
                            </button>
                            <div className="relative">
                              <button
                                onClick={() => setActiveMenu(activeMenu === `maint-${machine.id}` ? null : `maint-${machine.id}`)}
                                className="p-2 rounded-xl bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-700 hover:bg-slate-700 transition-all"
                              >
                                <ChevronDown className="w-4 h-4" />
                              </button>
                              {activeMenu === `maint-${machine.id}` && (
                                <div className="absolute left-0 mt-2 w-48 rounded-xl bg-slate-800 border border-slate-700 shadow-xl z-50 overflow-hidden">
                                  <div className="p-2 text-xs text-slate-400 font-medium border-b border-slate-700 text-right">
                                    הפעל לזמן קצוב:
                                  </div>
                                  <button
                                    onClick={() => { onToggleMaintenance?.(machine.id, 15); setActiveMenu(null); }}
                                    className="w-full text-right px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 transition-colors"
                                  >
                                    15 דקות
                                  </button>
                                  <button
                                    onClick={() => { onToggleMaintenance?.(machine.id, 60); setActiveMenu(null); }}
                                    className="w-full text-right px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 transition-colors"
                                  >
                                    שעה
                                  </button>
                                  <button
                                    onClick={() => { onToggleMaintenance?.(machine.id, 240); setActiveMenu(null); }}
                                    className="w-full text-right px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 transition-colors"
                                  >
                                    4 שעות
                                  </button>
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>

                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
