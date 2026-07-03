<template>
  <main class="login-shell">
    <section class="login-panel">
      <p class="eyebrow">Admin</p>
      <h1>灵镜后台管理</h1>
      <p class="login-copy">使用管理员账号登录，只有管理员账号可以进入。</p>

      <el-alert
        v-if="networkError"
        class="network-alert"
        type="error"
        show-icon
        :closable="true"
        title="无法连接远程服务器"
        :description="networkErrorMsg"
        @close="$emit('close-network-error')"
      />

      <el-form class="login-form" :model="loginForm" label-position="top" @submit.prevent="handleLogin">
        <el-form-item label="用户名">
          <el-input v-model="loginForm.username" size="large" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="loginForm.password"
            size="large"
            type="password"
            autocomplete="current-password"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loginLoading" @click="handleLogin">登录</el-button>
      </el-form>
    </section>
  </main>
</template>

<script setup lang="ts">
import { reactive } from 'vue';

defineProps<{
  loginLoading: boolean;
  networkError: boolean;
  networkErrorMsg: string;
}>();

const emit = defineEmits<{
  login: [username: string, password: string];
  'close-network-error': [];
}>();

const loginForm = reactive({ username: '', password: '' });

function handleLogin() {
  emit('login', loginForm.username.trim(), loginForm.password);
}
</script>

<style scoped>
.login-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px;
}

.login-panel {
  width: min(440px, 100%);
  padding: 34px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #c7d4e0;
  border-radius: 8px;
  box-shadow: 0 22px 60px rgba(50, 80, 110, 0.18);
}

.eyebrow {
  margin: 0 0 6px;
  color: #3a7bbf;
  font-weight: 800;
  letter-spacing: 0;
}

h1,
p {
  margin-top: 0;
}

.login-panel h1 {
  margin-bottom: 8px;
  font-size: 30px;
}

.login-copy {
  color: #607990;
}

.network-alert {
  margin-top: 16px;
}

.login-form {
  margin-top: 22px;
}

.login-form .el-button {
  width: 100%;
}
</style>
