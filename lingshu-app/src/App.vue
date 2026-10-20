<template>
  <router-view />
</template>

<script setup>
import { onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from './stores/auth';

const router = useRouter();
const auth = useAuthStore();

onMounted(async () => {
  await auth.init();
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
</script>
