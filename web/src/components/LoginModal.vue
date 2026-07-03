<script setup lang="ts">
import { ref, watch } from 'vue';
import { User, Lock } from '@element-plus/icons-vue';
import { useAuth } from '../stores/auth';

const auth = useAuth();

const mode = ref<'login' | 'register'>('login');

/* ---- 登录表单 ---- */
const loginUsername = ref('');
const loginPassword = ref('');
const loginError = ref('');

/* ---- 注册表单 ---- */
const regUsername = ref('');
const regPassword = ref('');
const regConfirm = ref('');
const regError = ref('');

watch(() => auth.showLoginModal, (val) => {
  if (val) {
    mode.value = 'login';
    loginUsername.value = '';
    loginPassword.value = '';
    loginError.value = '';
    regUsername.value = '';
    regPassword.value = '';
    regConfirm.value = '';
    regError.value = '';
  }
});

function switchToRegister() {
  regUsername.value = '';
  regPassword.value = '';
  regConfirm.value = '';
  regError.value = '';
  mode.value = 'register';
}

function switchToLogin() {
  mode.value = 'login';
}

async function handleLogin() {
  loginError.value = '';
  if (!loginUsername.value.trim()) { loginError.value = '请输入用户名'; return; }
  if (!loginPassword.value) { loginError.value = '请输入密码'; return; }
  try {
    await auth.login(loginUsername.value.trim(), loginPassword.value);
  } catch (e: any) {
    loginError.value = e.message;
  }
}

async function handleRegister() {
  regError.value = '';
  if (!regUsername.value.trim()) { regError.value = '请输入用户名'; return; }
  if (!regPassword.value) { regError.value = '请输入密码'; return; }
  if (regPassword.value.length < 8) { regError.value = '密码长度不能少于 8 位'; return; }
  if (!/[a-zA-Z]/.test(regPassword.value)) { regError.value = '密码必须包含字母'; return; }
  if (!/\d/.test(regPassword.value)) { regError.value = '密码必须包含数字'; return; }
  if (regPassword.value !== regConfirm.value) { regError.value = '两次密码不一致'; return; }
  try {
    await auth.register(regUsername.value.trim(), regPassword.value, true);
  } catch (e: any) {
    regError.value = e.message;
  }
}
</script>

<template>
  <el-dialog
    :model-value="auth.showLoginModal"
    :title="mode === 'login' ? '账号登录' : '注册账号'"
    width="380px"
    :close-on-click-modal="false"
    @close="auth.showLoginModal = false"
  >
    <Transition name="form-slide" mode="out-in">
      <!-- ===== 登录模式 ===== -->
      <div v-if="mode === 'login'" key="login" class="login-body">
        <el-input
          v-model="loginUsername"
          :prefix-icon="User"
          placeholder="用户名"
          size="large"
          @keyup.enter="handleLogin"
        />
        <el-input
          v-model="loginPassword"
          :prefix-icon="Lock"
          type="password"
          placeholder="密码"
          size="large"
          show-password
          @keyup.enter="handleLogin"
        />
        <div v-if="loginError" class="login-error">{{ loginError }}</div>
      </div>

      <!-- ===== 注册模式 ===== -->
      <div v-else key="register" class="login-body">
        <el-input
          v-model="regUsername"
          :prefix-icon="User"
          placeholder="用户名"
          size="large"
          @keyup.enter="handleRegister"
        />
        <el-input
          v-model="regPassword"
          :prefix-icon="Lock"
          type="password"
          placeholder="密码（至少 8 位，含字母和数字）"
          size="large"
          show-password
          @keyup.enter="handleRegister"
        />
        <el-input
          v-model="regConfirm"
          :prefix-icon="Lock"
          type="password"
          placeholder="确认密码"
          size="large"
          show-password
          @keyup.enter="handleRegister"
        />
        <div v-if="regError" class="login-error">{{ regError }}</div>
      </div>
    </Transition>

    <template #footer>
      <span class="dialog-footer">
        <Transition name="fade" mode="out-in">
          <a v-if="mode === 'login'" key="to-reg" class="switch-link" @click="switchToRegister">注册账号</a>
          <a v-else key="to-login" class="switch-link" @click="switchToLogin">返回登录</a>
        </Transition>
        <span class="btn-group">
          <el-button @click="auth.showLoginModal = false">取消</el-button>
          <el-button
            type="primary"
            :loading="auth.loading"
            @click="mode === 'login' ? handleLogin() : handleRegister()"
          >
            {{ mode === 'login' ? '登录' : '注册' }}
          </el-button>
        </span>
      </span>
    </template>
  </el-dialog>
</template>

<style scoped>
.login-body {
  display: grid;
  gap: 14px;
  padding: 4px 0 8px;
}
.login-error {
  color: #E53935;
  font-size: 13px;
}
.dialog-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}
.btn-group {
  display: flex;
  gap: 8px;
}
.switch-link {
  cursor: pointer;
  color: var(--el-color-primary, #1A8FC4);
  font-size: 14px;
  text-decoration: none;
}
.switch-link:hover {
  text-decoration: underline;
}

/* ---------- 切换动画 ---------- */
.form-slide-enter-active,
.form-slide-leave-active {
  transition: all 0.25s ease-out;
}
.form-slide-enter-from {
  opacity: 0;
  transform: translateX(24px);
}
.form-slide-leave-to {
  opacity: 0;
  transform: translateX(-24px);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
