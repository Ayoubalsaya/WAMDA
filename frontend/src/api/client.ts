// عميل HTTP رقيق — كوكي الجلسة/CSRF عبر credentials:'include'، لا تخزين
// رمز الجلسة في JS أبداً (HttpOnly من الخادم). §٩.

// خطأ تحقق واحد من الخادم (٤٢٢) بعد ترجمته إلى العربية — انظر app/validation_errors.py.
// `loc` مسار الحقل داخل الجسم (بلا «body»)، `label` اسمه الافتراضي (تتجاوزه كل شاشة
// بما يظهر عندها)، `message` نص عربي بلا اسم الحقل.
export interface FieldError {
  loc: (string | number)[]
  field: string | null
  label: string | null
  message: string
  type: string
}

export class ApiError extends Error {
  status: number
  fieldErrors: FieldError[]
  constructor(status: number, message: string, fieldErrors: FieldError[] = []) {
    super(message)
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

// لا يصل المستخدم JSON خام أبداً: النص المعروض عربي دائماً مهما كان شكل الرد.
const GENERIC_HTTP_MESSAGE = (status: number) => `تعذّر تنفيذ الطلب (خطأ ${status})`
const GENERIC_INVALID_DATA = 'بيانات غير صالحة — راجع الحقول المُدخَلة'

function humanMessage(status: number, data: unknown): string {
  const d = data as { detail?: unknown; message?: unknown } | undefined
  const raw = d && (d.detail ?? d.message)
  if (typeof raw === 'string' && raw.trim()) return raw
  if (status === 422) return GENERIC_INVALID_DATA  // قائمة/كائن خام (مصدر غير مترجَم) — لا يُعرض أبداً
  return GENERIC_HTTP_MESSAGE(status)
}

function fieldErrorsOf(data: unknown): FieldError[] {
  const errors = (data as { errors?: unknown } | undefined)?.errors
  if (!Array.isArray(errors)) return []
  return errors.filter((e): e is FieldError => !!e && typeof e === 'object' && typeof (e as FieldError).message === 'string')
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
  let res: Response
  try {
    res = await fetch(path, {
      method,
      credentials: 'include',
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    // انقطاع شبكة: رسالة المتصفح الإنجليزية («Failed to fetch») لا تُعرض
    throw new ApiError(0, 'تعذّر الاتصال بالخادم — تحقّق من الاتصال وأعد المحاولة')
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  let data: unknown
  try {
    data = text ? JSON.parse(text) : undefined
  } catch {
    if (!res.ok) throw new ApiError(res.status, GENERIC_HTTP_MESSAGE(res.status))
    throw new ApiError(res.status, 'ردّ غير متوقع من الخادم')
  }
  if (!res.ok) {
    // جلسة منتهية (خمول/سقف) أثناء الاستخدام → الشاشة تعود لتسجيل الدخول بدل البقاء معروضة بلا جلسة. مسارات الدخول/الهوية تُعالج 401 بنفسها.
    if (res.status === 401 && !/^\/(auth|portal)\/(login|me|logout)/.test(path)) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
    }
    throw new ApiError(res.status, humanMessage(res.status, data), fieldErrorsOf(data))
  }
  return data as T
}

export const SESSION_EXPIRED_EVENT = 'wamda:session-expired'

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  // استعلام آلي بلا مستخدم (جرس الإشعارات): لا يجدّد مهلة الخمول في الخادم (X-Wamda-Background)
  getBackground: <T>(path: string) => request<T>('GET', path, undefined, { 'X-Wamda-Background': '1' }),
  post: <T>(path: string, body?: unknown, idempotencyKey?: string) =>
    request<T>('POST', path, body, idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
}

// §هـ: مفتاح التفرّد يُولَّد في المتصفح عند بدء ملء النموذج — لا عند
// الضغط على حفظ — fetchIdempotencyKey يُستدعى مرة واحدة لكل جلسة نموذج.
export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}
