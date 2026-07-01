import {useState} from 'react';
import type {ViewState} from './types';
import {Sidebar} from './components/Sidebar';
import {Dashboard} from './components/Dashboard';
import {History} from './components/History';
import {Settings} from './components/Settings';
import {MachineList} from './components/MachineList';
import {Approvals} from './components/Approvals';
import {Predictions} from './components/Predictions';
import {Evidence} from './components/Evidence';
import {Chat} from './components/Chat';
import {DataProvider, useData} from './context/DataContext';

function AppShell() {
  const [currentView, setCurrentView] = useState<ViewState>('dashboard');
  const {
    alerts,
    machines,
    error,
    toggleAcknowledge,
    updateAlertStatus,
    snooze,
    toggleMaintenance,
    requestMachineAction,
  } = useData();

  return (
    <div className="flex h-screen bg-slate-950 overflow-hidden text-slate-200 font-sans" dir="rtl">
      <Sidebar currentView={currentView} onChangeView={setCurrentView} />

      <main className="flex-1 overflow-y-auto relative bg-slate-950">
        {error ? (
          <div className="absolute left-6 top-6 z-20 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs text-rose-200">
            API connection issue. Showing the latest available data.
          </div>
        ) : null}
        <div className="relative z-10 min-h-full">
          {currentView === 'dashboard' && (
            <Dashboard
              machines={machines}
              alerts={alerts}
              onUpdateAlertStatus={updateAlertStatus}
              onSnoozeAlert={snooze}
            />
          )}
          {currentView === 'machines' && (
            <MachineList
              machines={machines}
              onToggleMaintenance={toggleMaintenance}
              onMachineAction={requestMachineAction}
            />
          )}
          {currentView === 'history' && (
            <History
              alerts={alerts}
              onToggleAcknowledge={toggleAcknowledge}
              onUpdateAlertStatus={updateAlertStatus}
              onSnoozeAlert={snooze}
            />
          )}
          {currentView === 'approvals' && <Approvals />}
          {currentView === 'predictions' && <Predictions />}
          {currentView === 'evidence' && <Evidence />}
          {currentView === 'chat' && <Chat />}
          {currentView === 'settings' && <Settings />}
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <DataProvider>
      <AppShell />
    </DataProvider>
  );
}
