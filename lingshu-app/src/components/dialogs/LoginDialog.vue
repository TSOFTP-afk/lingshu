<template>
  <el-dialog
    v-model="visible"
    class="login-dialog"
    width="420px"
    append-to-body
    destroy-on-close
    :close-on-click-modal="false"
    aria-labelledby="login-dialog-title"
  >
    <template #header>
      <div class="dialog-head">
        <div class="login-avatar">
          {{ avatarInitial }}
        </div>
        <div>
          <h3 id="login-dialog-title">登录灵枢</h3>
          <p>{{ activeTab === 'login' ? '连接账号后保留本地创作流程' : '创建一个灵枢账号' }}</p>
        </div>
      </div>
    </template>

    <el-tabs
      v-model="activeTab"
      stretch
      class="login-tabs"
    >
      <el-tab-pane
        label="登录"
        name="login"
      />
      <el-tab-pane
        label="注册"
        name="register"
      />
    </el-tabs>

    <el-form
      label-position="top"
      class="login-form"
      @submit.prevent
    >
      <el-form-item label="用户名">
        <el-input
          v-model.trim="form.username"
          :prefix-icon="User"
          maxlength="40"
          autocomplete="username"
        />
      </el-form-item>
      <el-form-item label="密码">
        <el-input
          v-model="form.password"
          :prefix-icon="Lock"
          type="password"
          show-password
          maxlength="100"
          autocomplete="current-password"
          @keydown.enter.prevent="submit"
        />
      </el-form-item>
      <el-form-item
        v-if="activeTab === 'register'"
        label="确认密码"
      >
        <el-input
          v-model="form.confirmPassword"
          :prefix-icon="Lock"
          type="password"
          show-password
          maxlength="100"
          autocomplete="new-password"
          @keydown.enter.prevent="submit"
        />
      </el-form-item>
    </el-form>

    <el-checkbox
      v-model="agreedToTerms"
      class="terms-checkbox"
    >
      已阅读并同意《用户服务协议》及《隐私政策》
    </el-checkbox>

    <el-alert
      v-if="auth.error"
      class="login-error"
      :title="auth.error"
      type="error"
      show-icon
      :closable="false"
    />

    <template #footer>
      <div class="dialog-actions">
        <el-button @click="visible = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="auth.loading"
          @click="submit"
        >
          {{ activeTab === 'login' ? '登录' : '注册并登录' }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { Lock, User } from '@element-plus/icons-vue';
import { useAuthStore } from '../../stores/auth';

const props = defineProps({
  modelValue: { type: Boolean, default: false },
});
const emit = defineEmits(['update:modelValue']);

const auth = useAuthStore();
const activeTab = ref('login');
const agreedToTerms = ref(false);
const form = reactive({
  username: '',
  password: '',
  confirmPassword: '',
});

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
});

const avatarInitial = computed(() => {
  const source = form.username || auth.user?.username || '灵';
  return String(source).trim().slice(0, 1).toUpperCase() || '灵';
});

watch(visible, (value) => {
  if (value && auth.user?.username) {
    form.username = auth.user.username;
  }
});

async function submit() {
  const username = form.username.trim();
  const password = form.password;
  if (!username) {
    ElMessage.warning('请输入用户名');
    return;
  }
  if (!password) {
    ElMessage.warning('请输入密码');
    return;
  }
  if (activeTab.value === 'register') {
    if (password.length < 8) {
      ElMessage.warning('密码长度不能少于 8 位');
      return;
    }
    if (!/[a-zA-Z]/.test(password)) {
      ElMessage.warning('密码必须包含字母');
      return;
    }
    if (!/\d/.test(password)) {
      ElMessage.warning('密码必须包含数字');
      return;
    }
    if (password !== form.confirmPassword) {
      ElMessage.warning('两次输入的密码不一致');
      return;
    }
  }

  try {
    if (activeTab.value === 'login') {
      await auth.login(username, password);
      ElMessage.success('登录成功');
    } else {
      await auth.register(username, password, 1);
      ElMessage.success('注册成功');
    }
    form.password = '';
    form.confirmPassword = '';
    visible.value = false;
  } catch (e) {
    ElMessage.error(auth.error || e?.response?.data?.detail || e?.message || '登录失败');
  }
}
</script>

<style scoped>
.dialog-head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.login-avatar {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 9px;
  color: #fff;
  background: linear-gradient(135deg, #13b5a8, #4169e1);
  font-size: 20px;
  font-weight: 800;
  box-shadow: 0 8px 18px rgba(15, 143, 134, 0.22);
}

.dialog-head h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
  line-height: 1.3;
}

.dialog-head p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.login-tabs {
  margin-top: 2px;
}

.login-form {
  margin-top: 4px;
}

.terms-checkbox {
  margin-top: 12px;
}

.login-error {
  margin-top: 12px;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}


</style>
