import type {
  AuditEvent,
  DashboardData,
  Identity,
  MonitorOverrideMap,
  MonitorSettings,
} from './types'

interface ApiEnvelope<T> {
  success: boolean
  data: T
  error?: string
  code?: string
  request_id?: string
  fields?: Record<string, string>
  current?: MonitorSettings
}

export class ApiError extends Error {
  status: number
  code?: string
  requestId?: string
  fields?: Record<string, string>
  current?: MonitorSettings

  constructor(
    message: string,
    status: number,
    payload: Partial<ApiEnvelope<unknown>> = {},
    responseRequestId?: string | null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = payload.code
    this.requestId = payload.request_id || responseRequestId || undefined
    this.fields = payload.fields
    this.current = payload.current
  }
}

let csrfToken = ''

/** 返回普通用户统一登录入口，并兼容显式 Flask 开发源。 */
function loginUrl(): string {
  const origin = import.meta.env.VITE_FLASK_ORIGIN?.replace(/\/$/, '') || ''
  return `${origin}/`
}

/** 把失效或越权的管理员会话送回统一登录入口。 */
function redirectToLogin(): void {
  window.location.assign(loginUrl())
}

/** 强制从后端恢复实时身份，并缓存 Session 绑定的 CSRF token。 */
export async function loadIdentity(): Promise<Identity> {
  const response = await fetch('/api/check_auth', {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  })
  const data = (await response.json()) as Identity
  if (!data.isLoggedIn || data.role !== 'admin' || !data.csrf_token) {
    redirectToLogin()
    throw new ApiError('管理员会话无效', response.status || 401)
  }
  csrfToken = data.csrf_token
  return data
}

/** 发送同源管理员 API 请求，并统一处理 CSRF、错误与 request ID。 */
async function apiRequest<T>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const method = (options.method || 'GET').toUpperCase()
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (options.body !== undefined) headers.set('Content-Type', 'application/json')
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    headers.set('X-CSRF-Token', csrfToken)
  }
  const response = await fetch(url, {
    ...options,
    method,
    headers,
    credentials: 'same-origin',
  })
  let payload: Partial<ApiEnvelope<T>>
  try {
    payload = (await response.json()) as Partial<ApiEnvelope<T>>
  } catch {
    throw new ApiError(
      `服务端返回了无效响应 (${response.status})`,
      response.status,
      {},
      response.headers.get('X-Request-ID'),
    )
  }
  if (!response.ok || payload.success === false) {
    const error = new ApiError(
      payload.error || `请求失败 (${response.status})`,
      response.status,
      payload,
      response.headers.get('X-Request-ID'),
    )
    if (
      response.status === 401 ||
      (response.status === 403 && payload.code !== 'csrf_invalid')
    ) {
      redirectToLogin()
    }
    throw error
  }
  return payload.data as T
}

export const adminApi = {
  /** 读取一次完整聚合看板。 */
  dashboard: () => apiRequest<DashboardData>('/api/admin/db/dashboard', { cache: 'no-store' }),
  /** 登记普通共享刷新。 */
  refresh: () => apiRequest<{ groups: string[]; requested_at: string }>(
    '/api/admin/db/refresh',
    { method: 'POST' },
  ),
  /** 登记独立完整性审计。 */
  runIntegrity: () => apiRequest<{ groups: string[]; requested_at: string }>(
    '/api/admin/db/integrity/run',
    { method: 'POST' },
  ),
  /** 读取七项在线配置和逐项来源。 */
  settings: () => apiRequest<MonitorSettings>('/api/admin/db/settings', { cache: 'no-store' }),
  /** 按乐观版本保存完整覆盖快照。 */
  saveSettings: (version: number, overrides: MonitorOverrideMap) =>
    apiRequest<MonitorSettings>('/api/admin/db/settings', {
      method: 'PUT',
      body: JSON.stringify({ version, overrides }),
    }),
  /** 按乐观版本重置全部覆盖。 */
  resetSettings: (version: number) =>
    apiRequest<MonitorSettings>('/api/admin/db/settings/reset', {
      method: 'POST',
      body: JSON.stringify({ version }),
    }),
  /** 按有界游标读取配置审计历史。 */
  settingsHistory: (limit = 20, beforeId?: number) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (beforeId !== undefined) params.set('before_id', String(beforeId))
    return apiRequest<{ items: AuditEvent[]; next_before_id: number | null }>(
      `/api/admin/db/settings/history?${params}`,
      { cache: 'no-store' },
    )
  },
  /** 清空后端 Session 并回到统一登录入口。 */
  logout: async () => {
    await fetch('/api/logout', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
    redirectToLogin()
  },
}
