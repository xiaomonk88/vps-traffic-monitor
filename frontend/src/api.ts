export class APIError extends Error { constructor(message: string, public status: number) { super(message) } }
let csrf = ''
export function setCSRF(value: string) { csrf = value }
export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, { method, credentials: 'same-origin', headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(method !== 'GET' ? { 'X-CSRF-Token': csrf } : {}) }, body: body === undefined ? undefined : JSON.stringify(body) })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    let detail = data.detail
    if (Array.isArray(detail)) detail = detail.map((v: any) => `${v.loc?.slice(1).join('.') || '输入'}：${v.msg}`).join('；')
    if (typeof detail === 'object') detail = detail.message
    if (response.status === 401 && !['/login', '/setup', '/me'].includes(path)) window.dispatchEvent(new Event('session-expired'))
    throw new APIError(detail || `请求失败（${response.status}）`, response.status)
  }
  return data as T
}
export const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败，请稍后重试'
export const units: Record<string, number> = { GB: 1e9, TB: 1e12, GiB: 1024 ** 3, TiB: 1024 ** 4 }
export function bytes(value: number | null | undefined, unit = 'GB', digits = 2) { return value == null ? '—' : `${(value / (units[unit] || 1e9)).toLocaleString('zh-CN', { maximumFractionDigits: digits })} ${unit}` }
export function trafficBytes(value: number | null | undefined, unit = 'GB') {
  if (value == null) return '—'
  const binary = unit.includes('iB'), base = binary ? 1024 : 1000
  const labels = binary ? ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'] : ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let amount = value, index = 0
  while (Math.abs(amount) >= base && index < labels.length - 1) { amount /= base; index++ }
  return `${amount.toLocaleString('zh-CN', { maximumFractionDigits: 2 })} ${labels[index]}`
}
export function dateTime(value?: number | null, zone = 'Asia/Shanghai') { return value ? new Intl.DateTimeFormat('zh-CN', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value * 1000)) : '—' }
export function shortDate(value?: number | null, zone = 'Asia/Shanghai') { return value ? new Intl.DateTimeFormat('zh-CN', { timeZone: zone, month: 'long', day: 'numeric' }).format(new Date(value * 1000)) : '待配置' }
export function ago(value?: number | null) { if (!value) return '尚未上报'; const seconds = Math.max(0, Date.now() / 1000 - value); return seconds < 60 ? `${Math.floor(seconds)} 秒前` : seconds < 3600 ? `${Math.floor(seconds / 60)} 分钟前` : seconds < 86400 ? `${Math.floor(seconds / 3600)} 小时前` : `${Math.floor(seconds / 86400)} 天前` }
export const statusLabels: Record<string, string> = { pending: '待安装', disabled: '已撤销', offline: '离线', error: '采集异常', syncing: '补报中', uncalibrated: '待校准', warning: '额度偏低', online: '在线' }
export const directions: Record<string, string> = { tx: '上传计费', rx: '下载计费', sum: '双向计费' }
export interface Profile { quota_bytes: number; unit: string; direction: string; timezone: string; next_reset: string; reset_day: number; reset_time: string }
export interface Usage { rx: number; tx: number; coverage: number; uncertain: boolean }
export interface Node { id: string; name: string; group_name: string; note: string; enrolled: number | null; disabled: number; status: string; online: boolean; fresh: boolean; heartbeat: number | null; last_data: number | null; remaining: number | null; used: number | null; percent: number | null; cycle_end: number | null; cycle_start: number | null; profile: Profile | null; meta: Record<string, any>; yesterday: Usage; today: Usage; checkpoint: { id: string; at: number } | null; history?: (Usage & { date: string })[]; calibrations?: { id: string; created: number; remaining: number; previous: number | null; note: string }[]; exhaustion_risk: boolean; forecast_days: number | null; uncertain?: boolean; proxy_name?: string }
export function metered(node: Node, usage: Usage) { return node.profile?.direction === 'rx' ? usage.rx : node.profile?.direction === 'sum' ? usage.rx + usage.tx : usage.tx }
