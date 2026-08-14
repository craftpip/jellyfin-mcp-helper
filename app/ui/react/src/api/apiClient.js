const BASE = '/api'
let token = (typeof localStorage !== 'undefined' && localStorage.getItem('jsort_panel_token')) || ''

export function setAuthToken(t) {
  token = t || ''
  if (token) localStorage.setItem('jsort_panel_token', token)
  else localStorage.removeItem('jsort_panel_token')
}

export function getAuthToken() {
  return token
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiCall(method, path, body) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = 'Bearer ' + token
  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = 'HTTP ' + res.status
    try {
      const json = await res.json()
      if (json && json.detail) detail = typeof json.detail === 'string' ? json.detail : JSON.stringify(json.detail)
    } catch (e) {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return null
  return res.json()
}

export const apiGet = (path) => apiCall('GET', path)
export const apiPost = (path, body) => apiCall('POST', path, body)
export const apiPatch = (path, body) => apiCall('PATCH', path, body)
export const apiDelete = (path, body) => apiCall('DELETE', path, body)
