import {Download, FileArchive} from 'lucide-react';
import {evidenceExportUrl, logDownloadUrl} from '../services/endpoints';

export function Evidence() {
  return (
    <div className="p-8 flex flex-col gap-6 animate-in fade-in duration-500" dir="rtl">
      <header>
        <h2 className="text-2xl font-bold text-white">ייצוא ראיות</h2>
        <p className="text-slate-400">הורדת ראיות חתומות של תיקונים ואודיט מאותו מקור (Flask).</p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <a
          href={evidenceExportUrl(24, 'json')}
          target="_blank"
          rel="noopener noreferrer"
          className="bg-slate-900 rounded-3xl border border-slate-800 p-6 hover:border-indigo-500/50 transition-colors"
        >
          <FileArchive className="w-8 h-8 text-indigo-400 mb-5" />
          <h3 className="text-lg font-semibold text-white">חבילת JSON מוטמעת</h3>
          <p className="text-sm text-slate-400 mt-2">ראיות אודיט ותיקונים מ-24 השעות האחרונות.</p>
        </a>

        <a
          href={evidenceExportUrl(24, 'file')}
          target="_blank"
          rel="noopener noreferrer"
          className="bg-slate-900 rounded-3xl border border-slate-800 p-6 hover:border-indigo-500/50 transition-colors"
        >
          <Download className="w-8 h-8 text-emerald-400 mb-5" />
          <h3 className="text-lg font-semibold text-white">כתיבת חבילה בשרת</h3>
          <p className="text-sm text-slate-400 mt-2">יוצר קובץ ראיות תחת תיקיית ה-state של הסוכן.</p>
        </a>

        <a
          href={logDownloadUrl('monitor')}
          target="_blank"
          rel="noopener noreferrer"
          className="md:col-span-2 bg-slate-900 rounded-3xl border border-slate-800 p-6 hover:border-indigo-500/50 transition-colors"
        >
          <Download className="w-8 h-8 text-slate-300 mb-5" />
          <h3 className="text-lg font-semibold text-white">הורדת יומן ניטור</h3>
          <p className="text-sm text-slate-400 mt-2">הורדת יומן האודיט של הניטור כאשר הוא קיים.</p>
        </a>
      </div>
    </div>
  );
}
