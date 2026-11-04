import { useSyncExternalStore } from 'react'
import { getJson, postJson } from '../lib/api'
import { showToast } from './toasts'

export interface SessionUser {
  id: number
  username: string
  organization?: string | null
  role: string
}

interface InitialState {
  authUser: SessionUser | null
  nextPath: string | null
}

interface SessionState {
  user: SessionUser | null
  nextPath: string | null
  hydrated: boolean
}

function readInitialState(): InitialState {
  const fallback: InitialState = { authUser: null, nextPath: null }
  const el = document.getElementById('app-initial-state')
  if (!el) {
    return fallback
  }
  try {
    return { ...fallback, ...JSON.parse(el.textContent || '{}') }
  } catch {
    return fallback
  }
}

const initialState = readInitialState()

let state: SessionState = {
  user: initialState.authUser || null,
  nextPath: initialState.nextPath || null,
  hydrated: Boolean(initialState.authUser),
}

const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function applySessionUser(user: SessionUser | null | undefined): SessionUser | null {
  state = { ...state, user: user || null, hydrated: true }
  listeners.forEach((listener) => listener())
  return state.user
}

export function getSessionState(): SessionState {
  return state
}

/** React hook: re-renders when the logged-in user changes. */
export function useSession(): SessionState {
  return useSyncExternalStore(subscribe, getSessionState, getSessionState)
}

let pendingSession: Promise<SessionUser | null> | null = null

/** Load the session from the backend once; later calls reuse the result. */
export function ensureSession(): Promise<SessionUser | null> {
  if (state.hydrated) {
    return Promise.resolve(state.user)
  }
  if (!pendingSession) {
    pendingSession = getJson<{ user: SessionUser | null }>('/api/web/session')
      .then((payload) => applySessionUser(payload.user))
      .catch(() => applySessionUser(null))
      .finally(() => {
        pendingSession = null
      })
  }
  return pendingSession
}

export function setSessionUser(user: SessionUser | null) {
  return applySessionUser(user)
}

export function clearSessionUser() {
  return applySessionUser(null)
}

/** Show a message to the user and record it in the backend log. */
export function pushFlash(message: unknown, category = 'success') {
  const text = String(message || '').trim()
  if (!text) {
    return
  }
  showToast(text, category)
  postJson('/api/web/client-log', {
    message: text,
    category,
    path: window.location.pathname,
    source: 'flash',
  }).catch(() => {})
}
