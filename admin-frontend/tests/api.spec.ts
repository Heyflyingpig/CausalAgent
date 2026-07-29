import { beforeEach, describe, expect, it, vi } from 'vitest'
import { adminApi, ApiError, loadIdentity } from '../src/api'

function jsonResponse(body: unknown, status = 200, requestId = 'response-request-id'): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'X-Request-ID': requestId }),
    json: async () => body,
  } as Response
}

describe('管理员类型化 API 客户端', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  it('从 check_auth 保存 Session CSRF，并附加到管理员写请求', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock
      .mockResolvedValueOnce(jsonResponse({
        isLoggedIn: true,
        username: 'admin',
        role: 'admin',
        csrf_token: 'csrf-value',
      }))
      .mockResolvedValueOnce(jsonResponse({
        success: true,
        data: {
          groups: ['realtime', 'sql_performance', 'capacity'],
          requested_at: '2026-07-25T00:00:00Z',
        },
      }))

    await loadIdentity()
    await adminApi.refresh()

    const [, options] = fetchMock.mock.calls[1]
    const headers = new Headers(options?.headers)
    expect(options?.method).toBe('POST')
    expect(headers.get('X-CSRF-Token')).toBe('csrf-value')
  })

  it('错误对象优先保留服务端 request ID 和字段错误', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock
      .mockResolvedValueOnce(jsonResponse({
        isLoggedIn: true,
        username: 'admin',
        role: 'admin',
        csrf_token: 'csrf-value',
      }))
      .mockResolvedValueOnce(jsonResponse({
        success: false,
        error: '校验失败',
        code: 'validation_error',
        request_id: 'payload-request-id',
        fields: { realtime_interval_seconds: '必须在 5 到 10 之间' },
      }, 400))

    await loadIdentity()
    const rejection = adminApi.saveSettings(1, {
      auto_refresh_enabled: null,
      realtime_interval_seconds: 4,
      sql_interval_seconds: null,
      table_capacity_interval_seconds: null,
      slow_query_warning_delta: null,
      integrity_enabled: null,
      integrity_interval_seconds: null,
    })

    await expect(rejection).rejects.toMatchObject({
      name: 'ApiError',
      status: 400,
      code: 'validation_error',
      requestId: 'payload-request-id',
      fields: { realtime_interval_seconds: '必须在 5 到 10 之间' },
    } satisfies Partial<ApiError>)
  })
})
