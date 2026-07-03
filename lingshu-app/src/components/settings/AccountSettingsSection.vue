<template>
  <section class="settings-section account-settings-section">
    <div class="section-heading">
      <div>
        <h2>账号</h2>
        <p>登录状态、云端服务器地址和当前本地连接信息。</p>
      </div>
      <div class="heading-actions">
        <el-button
          v-if="!auth.isLoggedIn"
          type="primary"
          @click="openLogin"
        >
          登录 / 注册
        </el-button>
        <el-button
          v-else
          @click="logout"
        >
          退出登录
        </el-button>
      </div>
    </div>

    <div class="settings-panel account-panel">
      <div class="account-summary">
        <div class="profile-avatar large">
          {{ accountInitial }}
        </div>
        <div class="account-copy">
          <h3>{{ accountName }}</h3>
          <p>{{ auth.isLoggedIn ? '已登录，AI、同步和账号能力可用' : '未登录，本地创作可用，AI 功能需要先登录' }}</p>
        </div>
        <el-tag
          :type="auth.isLoggedIn ? 'success' : 'info'"
          effect="plain"
        >
          {{ auth.isLoggedIn ? '已登录' : 'AI 未解锁' }}
        </el-tag>
      </div>

      <div class="setting-row compact">
        <div>
          <div class="setting-name">
            绑定手机号
          </div>
          <div class="setting-desc">
            未绑定
          </div>
        </div>
        <el-tag
          type="info"
          effect="plain"
        >
          未绑定
        </el-tag>
      </div>


      <div class="setting-row compact">
        <div>
          <div class="setting-name">
            绑定邮箱
          </div>
          <div class="setting-desc">
            未绑定
          </div>
        </div>
        <el-tag
          type="info"
          effect="plain"
        >
          未绑定
        </el-tag>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue';
import { ElMessage } from 'element-plus';
import { useEventBus } from '../../composables/useEventBus';
import { useAuthStore } from '../../stores/auth';

const auth = useAuthStore();

const accountName = computed(() => auth.user?.display_name || auth.user?.username || '灵枢本地用户');
const accountInitial = computed(() => String(accountName.value || '灵').trim().slice(0, 1).toUpperCase() || '灵');

function openLogin() {
  useEventBus().emit('lingshu:open-login');
}

function logout() {
  auth.logout();
  ElMessage.success('已退出登录');
}


</script>

<style scoped>
.settings-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.section-heading h2 {
  margin: 0;
  color: var(--settings-text);
  font-size: 28px;
  line-height: 1.2;
  letter-spacing: 0;
}

.section-heading p {
  margin: 8px 0 0;
  color: var(--settings-muted);
  font-size: 13px;
  line-height: 1.7;
}

.heading-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.settings-panel {
  border: 1px solid var(--settings-border);
  border-radius: 8px;
  background: var(--settings-panel);
  overflow: hidden;
}

.account-summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  padding: 18px;
  border-bottom: 1px solid var(--settings-border);
}

.profile-avatar {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 8px;
  color: #fff;
  background: linear-gradient(135deg, #13b5a8, #4169e1);
  font-weight: 800;
}

.profile-avatar.large {
  width: 56px;
  height: 56px;
  font-size: 22px;
}

.account-copy {
  min-width: 0;
}

.account-summary h3 {
  margin: 0;
  color: var(--settings-text);
  font-size: 17px;
}

.account-summary p {
  margin: 5px 0 0;
  color: var(--settings-muted);
  font-size: 13px;
}

.setting-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 380px);
  align-items: center;
  gap: 20px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--settings-border-soft);
}

.setting-row:last-child {
  border-bottom: 0;
}

.setting-row.compact {
  grid-template-columns: minmax(0, 1fr) auto;
  min-height: 68px;
}

.setting-name {
  color: var(--settings-text);
  font-size: 14px;
  font-weight: 700;
}

.setting-desc {
  margin-top: 5px;
  color: var(--settings-muted);
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}


@media (max-width: 680px) {
  .section-heading,
  .account-summary,
  .setting-row,
  .setting-row.compact {
    grid-template-columns: 1fr;
  }

  .setting-row {
    display: grid;
  }

  .heading-actions {
    justify-content: flex-start;
  }
}
</style>
