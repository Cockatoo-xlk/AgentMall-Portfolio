export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public ambiguous = false,
  ) {
    super(
      status === 401
        ? '登录失效，请重新登录后核对状态。'
        : status === 403
          ? '当前账号无权执行此操作。'
          : status === 404
            ? '内容不存在，或你没有访问权限。'
            : status === 409
              ? '价格、库存或版本已变化，请核对最新状态。'
              : status === 422
                ? '输入内容不符合要求，请检查后重试。'
                : ambiguous
                  ? '连接中断或请求超时，结果尚未确定，请先核对状态。'
                  : '暂时无法加载，请检查连接后重试。',
    )
  }
}
export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '操作未完成，请核对后重试。'
}
export class ApiClient {
  constructor(
    private token: string | null = null,
    private onUnauthorized?: () => void,
    private timeout = 15000,
  ) {}
  async request<T>(
    path: string,
    method: string,
    body?: unknown,
    key?: string,
    signal?: AbortSignal,
  ): Promise<T> {
    if (!path.startsWith('/') || path.startsWith('//')) throw new Error('Invalid API path')
    const controller = new AbortController()
    const abort = () => controller.abort()
    if (signal?.aborted) controller.abort()
    signal?.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(
      abort,
      path === '/agent/messages' ||
        /^\/agent\/threads\/[^/]+\/(runs|resume|runs\/[^/]+\/recover)$/.test(path)
        ? 190000
        : this.timeout,
    )
    try {
      const headers = new Headers({ Accept: 'application/json' })
      if (body !== undefined) headers.set('Content-Type', 'application/json')
      if (this.token) headers.set('Authorization', `Bearer ${this.token}`)
      if (key) headers.set('Idempotency-Key', key)
      const response = await fetch(`/api/v1${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
        cache: 'no-store',
      })
      if (!response.ok) {
        let code = 'HTTP_ERROR'
        try {
          const data = await response.json()
          if (typeof data.code === 'string' && /^[A-Z_]+$/.test(data.code)) code = data.code
        } catch {
          /* No raw bodies enter the UI. */
        }
        if (response.status === 401 && this.token) this.onUnauthorized?.()
        throw new ApiError(response.status, code, response.status >= 500 && method !== 'GET')
      }
      try {
        const data = await response.json()
        const serverTime = response.headers.get('X-Server-Time')
        // Fresh GET metadata stays outside canonical snapshot and idempotent response JSON.
        if (
          method === 'GET' &&
          /^\/proposals\/[^/?]+$/.test(path) &&
          serverTime &&
          data &&
          typeof data === 'object' &&
          !Array.isArray(data)
        )
          return { ...data, server_time: serverTime } as T
        return data as T
      } catch {
        throw new ApiError(0, 'INVALID_RESPONSE', method !== 'GET')
      }
    } catch (error) {
      if (error instanceof ApiError) throw error
      if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError')
      throw new ApiError(0, 'NETWORK_ERROR', method !== 'GET')
    } finally {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abort)
    }
  }
  get<T>(path: string, signal?: AbortSignal) {
    return this.request<T>(path, 'GET', undefined, undefined, signal)
  }
  post<T>(path: string, body: unknown, key?: string) {
    return this.request<T>(path, 'POST', body, key)
  }
  put<T>(path: string, body: unknown) {
    return this.request<T>(path, 'PUT', body)
  }
  delete<T>(path: string, body: unknown) {
    return this.request<T>(path, 'DELETE', body)
  }
}
