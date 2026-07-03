<template>
  <router-view />
  <LoginDialog v-model="showLogin" />
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import LoginDialog from './components/dialogs/LoginDialog.vue';
import { useAuthStore } from './stores/auth';
import { useEventBus } from './composables/useEventBus';

const auth = useAuthStore();
const showLogin = ref(false);
const { on, off } = useEventBus();

function openLogin() {
  showLogin.value = true;
}

function onAuthExpired() {
  auth.logout();
}

onMounted(() => {
  auth.init();
  on('lingshu:open-login', openLogin);
  on('lingshu:auth-expired', onAuthExpired);
});

onUnmounted(() => {
  off('lingshu:open-login', openLogin);
  off('lingshu:auth-expired', onAuthExpired);
});
</script>
