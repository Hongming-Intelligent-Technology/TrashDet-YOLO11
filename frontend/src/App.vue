<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { postJson } from './lib/api'
import { clearSessionUser, pushFlash, sessionState } from './stores/session'

const route = useRoute()
const router = useRouter()
const authUser = computed(() => sessionState.user)
const isAuthPage = computed(() => Boolean(route.meta?.guestOnly))
const isHomePage = computed(() => route.path === '/')
const allNavItems = [
  { to: '/', label: '首页', match: ['/'] },
  { to: '/robot', label: '机器人管理', match: ['/robot'] },
  { to: '/result', label: '检测结果', match: ['/result'] },
  { to: '/stats', label: '统计分析', match: ['/stats'] },
  { to: '/train', label: '继续训练', match: ['/train'] },
  { to: '/users', label: '个人中心', match: ['/users'] },
]
const navItems = computed(() => allNavItems)

function isActive(matchers) {
  return matchers.some((item) => route.path === item || route.path.startsWith(`${item}/`))
}

async function logout() {
  try {
    await postJson('/api/web/logout', {})
    clearSessionUser()
    pushFlash('已退出登录', 'success')
    await router.replace('/login')
  } catch (error) {
    pushFlash(error.message || '退出失败', 'error')
  }
}
</script>

<template>
  <div class="layout-main" :class="{ 'layout-main-auth': isAuthPage }">
    <div v-if="!isAuthPage" class="layout-header">
      <div class="layout-header-left">
        <div class="layout-nav">
          <RouterLink v-for="item in navItems" :key="item.to" :to="item.to" class="layout-nav-link"
            :class="{ active: isActive(item.match) }">
            {{ item.label }}
          </RouterLink>
        </div>
      </div>
      <div class="layout-header-right">
        <div class="layout-user-row">
          <template v-if="authUser">
            <span class="layout-user-label">用户：{{ authUser.username }}</span>
            <button type="button" class="layout-logout-btn" @click="logout">
              退出
            </button>
          </template>
          <template v-else>
            <RouterLink to="/login" class="layout-auth-link">登录</RouterLink>
            <RouterLink to="/register" class="layout-auth-link">注册</RouterLink>
          </template>
        </div>
      </div>
    </div>

    <div class="layout-page-container" :class="{
      'layout-page-auth': isAuthPage,
      'layout-page-home': isHomePage,
    }">
      <RouterView />
    </div>
  </div>
</template>

<style scoped>
.layout-main-auth {
  background-image:
    radial-gradient(circle at 14% 16%, rgba(207, 232, 219, 0.46), transparent 34%),
    radial-gradient(circle at 86% 82%, rgba(204, 170, 128, 0.24), transparent 32%),
    linear-gradient(160deg, rgba(237, 247, 242, 0.94), rgba(224, 239, 231, 0.96));
}

.layout-page-auth {
  padding: 0;
}

.layout-page-home {
  padding: 0;
}

.layout-header-right {
  justify-self: end;
  display: grid;
  justify-items: end;
  gap: 2px;
}

.layout-user-row {
  margin-bottom: 0;
}
</style>
