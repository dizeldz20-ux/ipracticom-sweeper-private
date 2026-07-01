import {Check, RefreshCw, X} from 'lucide-react';
import {approveProposal, rejectProposal} from '../services/endpoints';
import {useApprovals} from '../hooks/useApprovals';

export function Approvals() {
  const {approvals, loading, refetch} = useApprovals();

  const decide = (id: string, kind: 'approve' | 'reject') => {
    const op = kind === 'approve' ? approveProposal(id) : rejectProposal(id);
    void op.finally(refetch);
  };

  return (
    <div className="p-8 flex flex-col gap-6 animate-in fade-in duration-500" dir="rtl">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">תור אישורים</h2>
          <p className="text-slate-400">פעולות מסוכנות ממתינות כאן לאישור לפני ביצוע.</p>
        </div>
        <button
          onClick={refetch}
          className="p-2 rounded-xl bg-slate-800 text-slate-300 border border-slate-700 hover:bg-slate-700"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </header>

      <div className="bg-slate-900 rounded-3xl border border-slate-800 overflow-hidden">
        {loading ? (
          <div className="p-8 text-slate-500">טוען אישורים...</div>
        ) : approvals.length === 0 ? (
          <div className="p-8 text-slate-500">אין אישורים ממתינים.</div>
        ) : (
          <div className="divide-y divide-slate-800">
            {approvals.map((approval) => (
              <div key={approval.id} className="p-5 flex flex-col gap-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-white">{approval.action}</span>
                      <span className="text-xs text-slate-500" dir="ltr">{approval.id}</span>
                    </div>
                    <p className="text-sm text-slate-400 mt-2">{approval.reason}</p>
                  </div>
                  <span className="text-xs text-slate-500" dir="ltr">{new Date(approval.createdAt).toLocaleString()}</span>
                </div>
                <pre className="bg-slate-950 border border-slate-800 rounded-xl p-3 text-xs text-slate-300 overflow-x-auto" dir="ltr">
                  {approval.proposedCommand || '# no command'}
                </pre>
                <div className="flex justify-end gap-2">
                  <button
                    onClick={() => decide(approval.id, 'reject')}
                    className="flex items-center gap-2 px-3 py-2 rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20 text-sm"
                  >
                    <X className="w-4 h-4" />
                    דחה
                  </button>
                  <button
                    onClick={() => decide(approval.id, 'approve')}
                    className="flex items-center gap-2 px-3 py-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 text-sm"
                  >
                    <Check className="w-4 h-4" />
                    אשר
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
