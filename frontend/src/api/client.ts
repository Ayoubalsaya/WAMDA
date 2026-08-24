// عميل HTTP رقيق — كوكي الجلسة/CSRF عبر credentials:'include'، لا تخزين
// رمز الجلسة في JS أبداً (HttpOnly من الخادم). §٩.

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function readCsrfCookie(): string | null {
  const match = document.cookie.match(/(?:^|; )wamda_csrf=([^;]*)/)
  return match ? decodeURIComponent(match[1]) : null
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const headers: Record<string, string> = { ...extraHeaders }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') {
    const csrf = readCsrfCookie()
    if (csrf) headers['X-CSRF-Token'] = csrf
  }
  const res = await fetch(path, {
    method,
    credentials: 'include',
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (res.status === 204) return undefined as T
  const text = await res.text()
  const data = text ? JSON.parse(text) : undefined
  if (!res.ok) {
    const message = (data && (data.detail || data.message)) || `خطأ HTTP ${res.status}`
    throw new ApiError(res.status, typeof message === 'string' ? message : JSON.stringify(message))
  }
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown, idempotencyKey?: string) =>
    request<T>('POST', path, body, idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined),
}

// §هـ: مفتاح التفرّد يُولَّد في المتصفح عند بدء ملء النموذج — لا عند
// الضغط على حفظ — fetchIdempotencyKey يُستدعى مرة واحدة لكل جلسة نموذج.
export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}
