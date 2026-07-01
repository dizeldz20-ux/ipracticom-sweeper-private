// Typed wrappers around every agent endpoint the SPA uses.
// Return RAW agent shapes (see agentTypes.ts); adapters translate to UI types.

import {request, url} from './http';
import type {
  RawApprovals,
  RawConnector,
  RawFleet,
  RawFleetHost,
  RawFilterRules,
  RawHeatmap,
  RawHistory,
  RawNotificationSettings,
  RawPredictions,
  RawSnapshot,
  RawThresholds,
  RawUptime,
  RawV6AlertsResponse,
  RawV6Logs,
} from './agentTypes';

// --- Snapshot / fleet --------------------------------------------------------
export const getSnapshot = (signal?: AbortSignal) =>
  request<RawSnapshot>('/api/snapshot', {signal});

export const runSweep = () => request<RawSnapshot>('/api/run', {method: 'POST'});

export const getFleet = (signal?: AbortSignal) =>
  request<RawFleet>('/api/fleet', {signal});

export const getFleetHost = (host: string, signal?: AbortSignal) =>
  request<RawFleetHost>(`/api/fleet/${encodeURIComponent(host)}`, {signal});

// --- Alerts (v6 live feed) ---------------------------------------------------
export const getAlerts = (tab = 'all', signal?: AbortSignal) =>
  request<RawV6AlertsResponse>(`/v6/alerts?tab=${encodeURIComponent(tab)}`, {signal});

export const resolveAlert = (id: string, note?: string) =>
  request(`/v6/alerts/${encodeURIComponent(id)}/resolve`, {
    method: 'POST',
    form: note ? {note} : {},
  });

export const snoozeAlert = (id: string, durationMin: number) =>
  request(`/v6/alerts/${encodeURIComponent(id)}/snooze`, {
    method: 'POST',
    form: {duration_min: durationMin},
  });

// --- Machine actions (approval-gated) ---------------------------------------
export type MachineAction = 'agent_restart' | 'reboot' | 'ssm_connect';

export const machineAction = (host: string, action: MachineAction) =>
  request(`/v6/machines/${encodeURIComponent(host)}/action`, {
    method: 'POST',
    form: {action},
  });

export const setMaintenance = (host: string, durationMin: number) =>
  request(`/v6/machines/${encodeURIComponent(host)}/maintenance`, {
    method: 'POST',
    form: {duration_min: durationMin},
  });

export const clearMaintenance = (host: string) =>
  request(`/v6/machines/${encodeURIComponent(host)}/maintenance/off`, {method: 'POST'});

// --- Metrics / logs ----------------------------------------------------------
export const getHeatmap = (signal?: AbortSignal) =>
  request<RawHeatmap>('/v6/metrics/events_heatmap', {signal});

export const getUptime30d = (signal?: AbortSignal) =>
  request<RawUptime>('/v6/metrics/uptime_30d', {signal});

export const getV6Logs = (signal?: AbortSignal) =>
  request<RawV6Logs>('/v6/logs', {signal});

export const getHistory = (
  metric: string,
  params: {host?: string; hours?: number; limit?: number} = {},
  signal?: AbortSignal,
) => {
  const q = new URLSearchParams();
  if (params.host) q.set('host', params.host);
  if (params.hours) q.set('hours', String(params.hours));
  if (params.limit) q.set('limit', String(params.limit));
  const qs = q.toString();
  return request<RawHistory>(
    `/api/history/${encodeURIComponent(metric)}${qs ? `?${qs}` : ''}`,
    {signal},
  );
};

// --- Connectors (AWS SSM) ----------------------------------------------------
export const listConnectors = (signal?: AbortSignal) =>
  request<RawConnector[]>('/api/connectors', {signal});

export const createConnector = (body: {
  name: string;
  instance_id: string;
  region?: string;
  tags?: Record<string, string>;
  enabled?: boolean;
}) => request<RawConnector>('/api/connectors', {method: 'POST', json: body});

export const updateConnector = (name: string, body: Record<string, unknown>) =>
  request<RawConnector>(`/api/connectors/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    json: body,
  });

export const deleteConnector = (name: string) =>
  request<void>(`/api/connectors/${encodeURIComponent(name)}`, {method: 'DELETE'});

export const testConnector = (name: string) =>
  request<{ok: boolean; snapshot?: unknown; error?: string}>(
    `/api/connectors/${encodeURIComponent(name)}/test`,
    {method: 'POST'},
  );

// --- Approvals ---------------------------------------------------------------
export const listApprovals = (signal?: AbortSignal) =>
  request<RawApprovals>('/api/approvals', {signal});

export const approveProposal = (id: string) =>
  request(`/api/approvals/${encodeURIComponent(id)}/approve`, {method: 'POST'});

export const rejectProposal = (id: string) =>
  request(`/api/approvals/${encodeURIComponent(id)}/reject`, {method: 'POST'});

// --- Predictions / evidence --------------------------------------------------
export const getPredictions = (signal?: AbortSignal) =>
  request<RawPredictions>('/api/predictions', {signal});

export const evidenceExportUrl = (hours = 24, format: 'json' | 'file' = 'json') =>
  url(`/api/evidence/export?hours=${hours}&format=${format}`);

export const logDownloadUrl = (name: string) =>
  url(`/api/logs/download?name=${encodeURIComponent(name)}`);

// --- Settings ----------------------------------------------------------------
export const getNotificationSettings = (signal?: AbortSignal) =>
  request<RawNotificationSettings>('/api/settings/notifications', {signal});

export const updateNotificationSettings = (body: {
  telegram_bot_token?: string;
  telegram_chat_id?: string;
  slack_webhook_url?: string;
}) => request<{ok: boolean; error?: string}>('/api/settings/notifications', {
  method: 'PUT',
  json: body,
});

export const testNotification = (channel: 'telegram' | 'slack') =>
  request<{ok: boolean; message?: string; error?: string}>(
    '/api/settings/notifications/test',
    {method: 'POST', json: {channel}},
  );

export const getThresholds = (signal?: AbortSignal) =>
  request<RawThresholds>('/api/settings/thresholds', {signal});

export const getFilterRules = (signal?: AbortSignal) =>
  request<RawFilterRules>('/api/settings/filter_rules', {signal});
