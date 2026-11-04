import { Suspense, useEffect, type ReactNode } from 'react'
import { Link, Navigate, Route, Routes, matchPath, useLocation, useNavigate } from 'react-router'
import { errorMessage, postJson } from './lib/api'
import Toaster from './components/Toaster'
import { appRoutes, type RouteMeta } from './routes'
import { clearSessionUser, ensureSession, pushFlash, useSession } from './stores/session'
import './AppLayout.css'

const NAV_ITEMS = [
  { to: '/', label: '首页', match: ['/'] },
  { to: '/robot', label: '机器人管理', match: ['/robot'] },
  { to: '/result', label: '检测结果', match: ['/result'] },
  { to: '/stats', label: '统计分析', match: ['/stats'] },
  { to: '/train', label: '继续训练', match: ['/train'] },
  { to: '/users', label: '个人中心', match: ['/users'] },
]

function isActive(pathname: string, matchers: string[]) {
  return matchers.some((item) => pathname === item || pathname.startsWith(`${item}/`))
}

function classNames(...names: Array<string | false | null | undefined>) {
  return names.filter(Boolean).join(' ')
}

/** Replaces the Vue router `beforeEach` guard: login redirect, guest-only pages, page title. */
function RouteGate({ meta, children }: { meta: RouteMeta; children: ReactNode }) {
  const { user, hydrated } = useSession()
  const location = useLocation()

  useEffect(() => {
    if (!hydrated) {
      ensureSession()
    }
  }, [hydrated])

  useEffect(() => {
    document.title = meta.title ? `${meta.title} - TrashDet` : 'TrashDet'
  }, [meta.title])

  if (!hydrated) {
    return null
  }
  if (meta.requiresAuth && !user) {
    const next = `${location.pathname}${location.search}`
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />
  }
  if (meta.guestOnly && user) {
    return <Navigate to="/" replace />
  }
  return <>{children}</>
}

export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user } = useSession()

  const currentRoute = appRoutes.find((route) => matchPath(route.path, location.pathname))
  const isAuthPage = Boolean(currentRoute?.meta.guestOnly)
  const isHomePage = location.pathname === '/'

  useEffect(() => {
    window.scrollTo(0, 0)
  }, [location.pathname])

  async function logout() {
    try {
      await postJson('/api/web/logout', {})
      clearSessionUser()
      pushFlash('已退出登录', 'success')
      navigate('/login', { replace: true })
    } catch (error) {
      pushFlash(errorMessage(error, '退出失败'), 'error')
    }
  }

  return (
    <div className={classNames('scope-app', 'layout-main', isAuthPage && 'layout-main-auth')}>
      {!isAuthPage && (
        <div className="layout-header">
          <div className="layout-header-left">
            <div className="layout-nav">
              {NAV_ITEMS.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className={classNames('layout-nav-link', isActive(location.pathname, item.match) && 'active')}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          </div>
          <div className="layout-header-right">
            <div className="layout-user-row">
              {user ? (
                <>
                  <span className="layout-user-label">用户：{user.username}</span>
                  <button type="button" className="layout-logout-btn" onClick={logout}>
                    退出
                  </button>
                </>
              ) : (
                <>
                  <Link to="/login" className="layout-auth-link">登录</Link>
                  <Link to="/register" className="layout-auth-link">注册</Link>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      <div className={classNames('layout-page-container', isAuthPage && 'layout-page-auth', isHomePage && 'layout-page-home')}>
        <Suspense fallback={null}>
          <Routes>
            {appRoutes.map(({ path, component: Page, meta }) => (
              <Route
                key={path}
                path={path}
                element={
                  <RouteGate meta={meta}>
                    <Page />
                  </RouteGate>
                }
              />
            ))}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </div>
      <Toaster />
    </div>
  )
}
