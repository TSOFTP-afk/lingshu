<template>
  <router-view />
  <LoginDialog v-model="showLogin" />
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import LoginDialog from './components/dialogs/LoginDialog.vue';
import { useAuthStore } from './stores/auth';
import { useEventBus } from './composables/useEventBus';

const router = useRouter();
const auth = useAuthStore();
const showLogin = ref(false);
const { on, off } = useEventBus();

function openLogin() {
  showLogin.value = true;
}

function onAuthExpired() {
  auth.logout();
}

onMounted(async () => {
  await auth.init();
  on('lingshu:open-login', openLogin);
  on('lingshu:auth-expired', onAuthExpired);
  if (!auth.isLoggedIn) return; // 未登录不恢复路径

  const currentPath = router.currentRoute.value.fullPath;
  // 仅在用户落在 /workspace 根路径或 / 时尝试恢复
  if (currentPath === '/workspace' || currentPath === '/' || currentPath === '/workspace/') {
    const lastPath = localStorage.getItem('lingshu_last_workspace_path');
    if (lastPath && lastPath !== currentPath && lastPath.startsWith('/workspace')) {
      // 排除 settings 路径（不应被恢复为最后路径）
      if (!lastPath.startsWith('/workspace/settings')) {
        router.replace(lastPath);
      }
    }
  }
});

onUnmounted(() => {
  off('lingshu:open-login', openLogin);
  off('lingshu:auth-expired', onAuthExpired);
});
</script>
