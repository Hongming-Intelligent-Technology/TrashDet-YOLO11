import { createRouter, createWebHistory } from 'vue-router'
import { ensureSession } from './stores/session'

const HomePage = () => import('./views/HomePage.vue')
const LoginPage = () => import('./views/LoginPage.vue')
const RegisterPage = () => import('./views/RegisterPage.vue')
const StatsPage = () => import('./views/StatsPage.vue')
const ResultListPage = () => import('./views/ResultListPage.vue')
const ResultDetailPage = () => import('./views/ResultDetailPage.vue')
const RobotAdminPage = () => import('./views/RobotAdminPage.vue')
const RobotControlPage = () => import('./views/RobotControlPage.vue')
const TrainPage = () => import('./views/TrainPage.vue')
const UserAdminPage = () => import('./views/UserAdminPage.vue')

const routes = [
  { path: '/', name: 'home', component: HomePage, meta: { requiresAuth: true, title: '首页' } },
  { path: '/login', name: 'login', component: LoginPage, meta: { guestOnly: true, title: '用户登录' } },
  { path: '/register', name: 'register', component: RegisterPage, meta: { guestOnly: true, title: '用户注册' } },
  { path: '/stats', name: 'stats', component: StatsPage, meta: { requiresAuth: true, title: '数据分析' } },
  { path: '/result', name: 'results', component: ResultListPage, meta: { requiresAuth: true, title: '任务管理' } },
  { path: '/result/:id', name: 'result-detail', component: ResultDetailPage, meta: { requiresAuth: true, title: '任务详情' } },
  { path: '/robot', name: 'robot-admin', component: RobotAdminPage, meta: { requiresAuth: true, title: '机器人管理' } },
  { path: '/robot/:id', name: 'robot-control', component: RobotControlPage, meta: { requiresAuth: true, title: '机器人控制' } },
  { path: '/users', name: 'user-admin', component: UserAdminPage, meta: { requiresAuth: true, title: '个人中心' } },
  { path: '/train', name: 'train', component: TrainPage, meta: { requiresAuth: true, title: '训练模型' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const user = await ensureSession()

  if (to.meta.requiresAuth && !user) {
    return {
      name: 'login',
      query: { next: to.fullPath },
    }
  }

  if (to.meta.guestOnly && user) {
    return { name: 'home' }
  }

  document.title = `${to.meta.title || 'EcoGuard'} - TrashDet`
  return true
})

export default router
