import { lazy, type ComponentType, type LazyExoticComponent } from 'react'

export interface RouteMeta {
  requiresAuth?: boolean
  guestOnly?: boolean
  title: string
}

export interface AppRoute {
  path: string
  component: LazyExoticComponent<ComponentType>
  meta: RouteMeta
}

const HomePage = lazy(() => import('./views/HomePage'))
const LoginPage = lazy(() => import('./views/LoginPage'))
const RegisterPage = lazy(() => import('./views/RegisterPage'))
const StatsPage = lazy(() => import('./views/StatsPage'))
const ResultListPage = lazy(() => import('./views/ResultListPage'))
const ResultDetailPage = lazy(() => import('./views/ResultDetailPage'))
const RobotAdminPage = lazy(() => import('./views/RobotAdminPage'))
const RobotControlPage = lazy(() => import('./views/RobotControlPage'))
const TrainPage = lazy(() => import('./views/TrainPage'))
const UserAdminPage = lazy(() => import('./views/UserAdminPage'))

export const appRoutes: AppRoute[] = [
  { path: '/', component: HomePage, meta: { requiresAuth: true, title: '首页' } },
  { path: '/login', component: LoginPage, meta: { guestOnly: true, title: '用户登录' } },
  { path: '/register', component: RegisterPage, meta: { guestOnly: true, title: '用户注册' } },
  { path: '/stats', component: StatsPage, meta: { requiresAuth: true, title: '数据分析' } },
  { path: '/result', component: ResultListPage, meta: { requiresAuth: true, title: '任务管理' } },
  { path: '/result/:id', component: ResultDetailPage, meta: { requiresAuth: true, title: '任务详情' } },
  { path: '/robot', component: RobotAdminPage, meta: { requiresAuth: true, title: '机器人管理' } },
  { path: '/robot/:id', component: RobotControlPage, meta: { requiresAuth: true, title: '机器人控制' } },
  { path: '/users', component: UserAdminPage, meta: { requiresAuth: true, title: '个人中心' } },
  { path: '/train', component: TrainPage, meta: { requiresAuth: true, title: '训练模型' } },
]
