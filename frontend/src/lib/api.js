const JSON_HEADERS = {
  Accept: 'application/json',
}

async function parseJson(response) {
  if (response.status === 204) {
    return { ok: true }
  }

  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload.ok === false) {
    const message = payload.message || payload.msg || payload.error || `Request failed: ${response.status}`
    const error = new Error(message)
    error.status = response.status
    error.payload = payload
    throw error
  }
  return payload
}

export async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...JSON_HEADERS,
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(options.headers || {}),
    },
  })

  return parseJson(response)
}

export function getJson(url) {
  return requestJson(url, { method: 'GET' })
}

export function postJson(url, body) {
  return requestJson(url, {
    method: 'POST',
    body: JSON.stringify(body || {}),
  })
}

export async function postForm(url, formData) {
  return requestJson(url, {
    method: 'POST',
    body: formData,
  })
}
