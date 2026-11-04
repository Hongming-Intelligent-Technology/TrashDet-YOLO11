export type JsonObject = Record<string, any>

export class ApiError extends Error {
  status: number
  payload: JsonObject

  constructor(message: string, status: number, payload: JsonObject) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

/** Message of any thrown value, for user-facing error text. */
export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

const JSON_HEADERS = {
  Accept: 'application/json',
}

async function parseJson<T>(response: Response): Promise<T> {
  if (response.status === 204) {
    return { ok: true } as T
  }

  const payload: JsonObject = await response.json().catch(() => ({}))
  if (!response.ok || payload.ok === false) {
    const message = payload.message || payload.msg || payload.error || `Request failed: ${response.status}`
    throw new ApiError(message, response.status, payload)
  }
  return payload as T
}

export async function requestJson<T = JsonObject>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...JSON_HEADERS,
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(options.headers as Record<string, string> | undefined),
    },
  })

  return parseJson<T>(response)
}

export function getJson<T = JsonObject>(url: string): Promise<T> {
  return requestJson<T>(url, { method: 'GET' })
}

export function postJson<T = JsonObject>(url: string, body?: unknown): Promise<T> {
  return requestJson<T>(url, {
    method: 'POST',
    body: JSON.stringify(body || {}),
  })
}

export function postForm<T = JsonObject>(url: string, formData: FormData): Promise<T> {
  return requestJson<T>(url, {
    method: 'POST',
    body: formData,
  })
}
