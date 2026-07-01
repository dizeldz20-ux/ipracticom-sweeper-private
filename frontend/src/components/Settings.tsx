import {useEffect, useState} from 'react';
import {BellRing, Bot, Cloud, Cpu, Plus, Save, Shield, Terminal, Trash2} from 'lucide-react';
import type {FilterRule} from '../types';
import type {RawConnector, RawNotificationSettings, RawThresholds} from '../services/agentTypes';
import {
  createConnector,
  deleteConnector,
  getFilterRules,
  getNotificationSettings,
  getThresholds,
  listConnectors,
  testConnector,
  testNotification,
  updateNotificationSettings,
} from '../services/endpoints';

export function Settings() {
  const [notification, setNotification] = useState<RawNotificationSettings | null>(null);
  const [thresholds, setThresholds] = useState<RawThresholds | null>(null);
  const [rules, setRules] = useState<FilterRule[]>([]);
  const [rulesNote, setRulesNote] = useState('');
  const [connectors, setConnectors] = useState<RawConnector[]>([]);
  const [telegramToken, setTelegramToken] = useState('');
  const [chatId, setChatId] = useState('');
  const [slackWebhook, setSlackWebhook] = useState('');
  const [newConnector, setNewConnector] = useState({name: '', instance_id: '', region: 'il-central-1'});
  const [message, setMessage] = useState('');

  const load = async () => {
    const [notificationData, thresholdsData, filterData, connectorData] = await Promise.all([
      getNotificationSettings(),
      getThresholds(),
      getFilterRules(),
      listConnectors(),
    ]);
    setNotification(notificationData);
    setChatId(notificationData.telegram_chat_id || '');
    setThresholds(thresholdsData);
    setRules(filterData.rules || []);
    setRulesNote(filterData.note || '');
    setConnectors(connectorData);
  };

  useEffect(() => {
    void load().catch((err) => setMessage(err instanceof Error ? err.message : String(err)));
  }, []);

  const saveNotifications = async () => {
    await updateNotificationSettings({
      telegram_bot_token: telegramToken || undefined,
      telegram_chat_id: chatId,
      slack_webhook_url: slackWebhook || undefined,
    });
    setTelegramToken('');
    setSlackWebhook('');
    setMessage('הגדרות ההתראות נשמרו.');
    await load();
  };

  const addConnector = async () => {
    if (!newConnector.name || !newConnector.instance_id) return;
    await createConnector({...newConnector, enabled: true, tags: {}});
    setNewConnector({name: '', instance_id: '', region: newConnector.region});
    setMessage('המחבר נוסף.');
    await load();
  };

  const runConnectorTest = async (name: string) => {
    const result = await testConnector(name);
    setMessage(result.ok ? `המחבר ${name} תקין.` : result.error || `המחבר ${name} נכשל.`);
  };

  return (
    <div className="p-8 flex flex-col gap-6 animate-in fade-in duration-500 max-w-6xl mx-auto" dir="rtl">
      <header className="flex justify-between items-end">
        <div>
          <h2 className="text-2xl font-bold text-white">הגדרות סוכן</h2>
          {message ? <p className="text-sm text-indigo-300 mt-2">{message}</p> : null}
        </div>
        <button
          onClick={() => void saveNotifications().catch((err) => setMessage(err instanceof Error ? err.message : String(err)))}
          className="flex items-center gap-2 bg-indigo-500 hover:bg-indigo-400 text-white px-4 py-2 rounded-xl font-medium transition-colors text-sm"
        >
          <Save className="w-4 h-4" />
          שמור התראות
        </button>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-8 h-8 bg-[#0088cc] rounded-lg flex items-center justify-center">
                <Bot className="w-5 h-5 text-white" />
              </div>
              <h3 className="text-lg font-semibold text-white">Telegram / Slack</h3>
            </div>
            <div className="space-y-4">
              <input
                type="password"
                value={telegramToken}
                onChange={(e) => setTelegramToken(e.target.value)}
                placeholder={notification?.telegram_bot_token_set ? 'הטוקן מוגדר; השאר ריק כדי לשמור' : 'טוקן בוט'}
                className="w-full bg-slate-800/50 border border-slate-700 rounded-xl py-2 px-3 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                dir="ltr"
              />
              <input
                type="text"
                value={chatId}
                onChange={(e) => setChatId(e.target.value)}
                placeholder="מזהה צ׳אט טלגרם"
                className="w-full bg-slate-800/50 border border-slate-700 rounded-xl py-2 px-3 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                dir="ltr"
              />
              <input
                type="password"
                value={slackWebhook}
                onChange={(e) => setSlackWebhook(e.target.value)}
                placeholder={notification?.slack_webhook_set ? 'ה-webhook של Slack מוגדר; השאר ריק כדי לשמור' : 'כתובת webhook של Slack'}
                className="w-full bg-slate-800/50 border border-slate-700 rounded-xl py-2 px-3 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                dir="ltr"
              />
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => void testNotification('telegram').then((r) => setMessage(r.message || r.error || 'בוצע'))}
                  className="flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-300 px-4 py-2 rounded-xl text-sm transition-colors"
                >
                  <BellRing className="w-4 h-4 text-amber-400" />
                  Telegram
                </button>
                <button
                  onClick={() => void testNotification('slack').then((r) => setMessage(r.message || r.error || 'בוצע'))}
                  className="flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-300 px-4 py-2 rounded-xl text-sm transition-colors"
                >
                  <BellRing className="w-4 h-4 text-amber-400" />
                  Slack
                </button>
              </div>
            </div>
          </div>

          <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-8 h-8 bg-amber-500/20 rounded-lg flex items-center justify-center border border-amber-500/30">
                <Cpu className="w-5 h-5 text-amber-400" />
              </div>
              <h3 className="text-lg font-semibold text-white">ספים</h3>
            </div>
            <div className="space-y-3 text-sm text-slate-300">
              <div className="flex justify-between"><span>אזהרת עומס מעבד</span><span dir="ltr">{thresholds?.cpu?.load_avg_5min_warn ?? '-'}</span></div>
              <div className="flex justify-between"><span>עומס מעבד קריטי</span><span dir="ltr">{thresholds?.cpu?.load_avg_5min_crit ?? '-'}</span></div>
              <div className="flex justify-between"><span>אזהרת זיכרון</span><span dir="ltr">{thresholds?.memory?.used_percent_warn ?? '-'}%</span></div>
              <div className="flex justify-between"><span>זיכרון קריטי</span><span dir="ltr">{thresholds?.memory?.used_percent_crit ?? '-'}%</span></div>
              <div className="flex justify-between"><span>אזהרת דיסק</span><span dir="ltr">{thresholds?.disk?.used_percent_warn ?? '-'}%</span></div>
              <div className="text-xs text-slate-500 pt-3 border-t border-slate-800">לקריאה בלבד עד שייקבע נתיב כתיב לחוקים.</div>
            </div>
          </div>
        </div>

        <div className="lg:col-span-2 space-y-6">
          <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-8 h-8 bg-emerald-500/20 rounded-lg flex items-center justify-center border border-emerald-500/30">
                <Shield className="w-5 h-5 text-emerald-400" />
              </div>
              <h3 className="text-lg font-semibold text-white">חוקי סינון</h3>
            </div>
            {rules.length === 0 ? (
              <div className="text-sm text-slate-500">{rulesNote || 'לא נאכפים חוקי סינון עדיין.'}</div>
            ) : (
              <div className="space-y-3">
                {rules.map((rule) => (
                  <div key={rule.id} className="bg-slate-800/40 rounded-2xl p-4">
                    <div className="text-sm text-slate-200">{rule.name}</div>
                    <div className="text-xs text-slate-500 font-mono mt-1" dir="ltr">{rule.pattern}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="bg-slate-900 rounded-3xl border border-slate-800 p-6">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-sky-500/20 rounded-lg flex items-center justify-center border border-sky-500/30">
                  <Cloud className="w-5 h-5 text-sky-400" />
                </div>
                <h3 className="text-lg font-semibold text-white">מחברי AWS SSM</h3>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
              <input value={newConnector.name} onChange={(e) => setNewConnector({...newConnector, name: e.target.value})} placeholder="שם" className="bg-slate-800/50 border border-slate-700 rounded-xl py-2 px-3 text-sm text-slate-200" />
              <input value={newConnector.instance_id} onChange={(e) => setNewConnector({...newConnector, instance_id: e.target.value})} placeholder="מזהה Instance" className="bg-slate-800/50 border border-slate-700 rounded-xl py-2 px-3 text-sm text-slate-200" dir="ltr" />
              <div className="flex gap-2">
                <input value={newConnector.region} onChange={(e) => setNewConnector({...newConnector, region: e.target.value})} placeholder="אזור" className="min-w-0 flex-1 bg-slate-800/50 border border-slate-700 rounded-xl py-2 px-3 text-sm text-slate-200" dir="ltr" />
                <button onClick={() => void addConnector().catch((err) => setMessage(err instanceof Error ? err.message : String(err)))} className="p-2 rounded-xl bg-sky-500/10 text-sky-400 border border-sky-500/20 hover:bg-sky-500/20">
                  <Plus className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {connectors.length === 0 ? (
                <div className="text-sm text-slate-500">לא הוגדרו מחברים.</div>
              ) : connectors.map((connector) => (
                <div key={connector.name} className="bg-slate-800/50 rounded-2xl border border-slate-700/50 p-4 flex flex-col gap-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <h4 className="text-sm font-medium text-slate-200">{connector.name}</h4>
                      <div className="flex items-center gap-2 mt-2 font-mono text-xs text-slate-400" dir="ltr">
                        <Terminal className="w-3 h-3" />
                        {connector.instance_id}
                      </div>
                    </div>
                    <span className="text-[10px] font-bold px-2 py-1 bg-slate-700 text-slate-300 rounded uppercase tracking-wider">
                      {connector.region}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 pt-4 border-t border-slate-700/50">
                    <button onClick={() => void runConnectorTest(connector.name).catch((err) => setMessage(err instanceof Error ? err.message : String(err)))} className="flex-1 text-xs text-sky-400 hover:text-sky-300 bg-sky-500/10 hover:bg-sky-500/20 py-2 rounded-lg transition-colors text-center font-medium">
                      בדיקת חיבור
                    </button>
                    <button onClick={() => void deleteConnector(connector.name).then(load)} className="p-2 text-slate-500 hover:text-rose-400 hover:bg-rose-400/10 rounded-lg transition-colors">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
