import {
  Activity,
  BotMessageSquare,
  BrainCircuit,
  ClipboardCheck,
  FileArchive,
  History,
  LayoutDashboard,
  Settings,
  ShieldAlert,
} from 'lucide-react';
import type {ViewState} from '../types';

interface SidebarProps {
  currentView: ViewState;
  onChangeView: (view: ViewState) => void;
}

const navItems: Array<{id: ViewState; label: string; icon: typeof LayoutDashboard}> = [
  {id: 'dashboard', label: 'לוח בקרה', icon: LayoutDashboard},
  {id: 'machines', label: 'מכונות', icon: Activity},
  {id: 'history', label: 'היסטוריית אירועים', icon: History},
  {id: 'approvals', label: 'אישורים', icon: ClipboardCheck},
  {id: 'predictions', label: 'תחזיות', icon: BrainCircuit},
  {id: 'evidence', label: 'ראיות', icon: FileArchive},
  {id: 'chat', label: 'עוזר AI', icon: BotMessageSquare},
  {id: 'settings', label: 'הגדרות', icon: Settings},
];

export function Sidebar({currentView, onChangeView}: SidebarProps) {
  return (
    <aside className="w-64 bg-slate-900 border-l border-slate-800 flex flex-col p-6 relative z-20">
      <div className="flex items-center gap-3 mb-10">
        <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
          <ShieldAlert className="w-5 h-5 text-white" />
        </div>
        <h1 className="text-xl font-bold tracking-tight text-white">Sweeper Agent</h1>
      </div>

      <nav className="flex flex-col gap-2 flex-1" dir="rtl">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onChangeView(item.id)}
              className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-colors ${
                isActive
                  ? 'bg-indigo-600/10 text-indigo-400 border border-indigo-600/20'
                  : 'text-slate-400 hover:bg-slate-800 border border-transparent'
              }`}
            >
              <Icon className="w-5 h-5" />
              <span className="text-sm font-semibold">{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="mt-auto" dir="rtl">
        <div className="p-4 bg-slate-800/50 rounded-2xl border border-slate-700/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-slate-400">סטטוס חיבור</span>
            <div className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
          </div>
          <p className="text-xs text-slate-300 font-mono" dir="ltr">Same-origin API</p>
        </div>
      </div>
    </aside>
  );
}
