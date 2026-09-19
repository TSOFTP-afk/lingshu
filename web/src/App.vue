<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Bell, Collection, Search, User } from '@element-plus/icons-vue';
import { useAuth } from './stores/auth';
import LoginModal from './components/LoginModal.vue';

const auth = useAuth();
const router = useRouter();
const route = useRoute();
const globalKeyword = ref(String(route.query.q || ''));

watch(
  () => route.query.q,
  (value) => {
    globalKeyword.value = String(value || '');
  },
);

function runGlobalSearch() {
  const q = globalKeyword.value.trim();
  router.push({ path: '/bookstore', query: q ? { q } : {} });
}

onMounted(() => {
  void auth.fetchMe();
});
</script>

<template>
  <el-config-provider>
    <div class="app-shell">
      <header class="site-header">
        <div class="site-header-inner">
          <RouterLink class="site-logo" to="/">
            <strong>灵爻</strong>
            <span>AI共创阅读平台</span>
          </RouterLink>

          <nav class="site-nav" aria-label="主导航">
            <RouterLink class="site-nav-link" to="/">首页</RouterLink>
            <RouterLink class="site-nav-link" to="/bookstore">书库</RouterLink>
          </nav>

          <div class="site-search">
            <el-input
              v-model="globalKeyword"
              :prefix-icon="Search"
              clearable
              placeholder="搜书名、作者、关键词"
              @keyup.enter="runGlobalSearch"
              @clear="runGlobalSearch"
            />
          </div>

        <div class="site-actions">
            <el-button :icon="Collection" text @click="router.push('/shelf')">书箱</el-button>
            <el-badge is-dot class="message-badge">
              <el-button :icon="Bell" text aria-label="消息" />
            </el-badge>
            <template v-if="auth.user">
              <el-button :icon="User" text @click="router.push('/profile')">{{ auth.user.username }}</el-button>
              <el-button text size="small" @click="auth.logout()">退出</el-button>
            </template>
            <el-button v-else :icon="User" text @click="auth.openLogin()">登录</el-button>
          </div>
        </div>
      </header>
      <main>
        <RouterView />
      </main>
      <LoginModal />
    </div>
  </el-config-provider>
</template>
