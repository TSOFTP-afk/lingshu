<template>
  <div class="community-view">
    <header class="community-topbar">
      <el-button
        class="back-button"
        @click="backToWorkspace"
      >
        <el-icon><ArrowLeft /></el-icon>
        <span>返回工作台</span>
      </el-button>
      <h1 class="community-title">
        卡片社区
      </h1>
      <el-button
        type="primary"
        :disabled="!auth.isLoggedIn"
        :title="auth.isLoggedIn ? '' : '请先登录'"
        @click="showUpload = true"
      >
        <el-icon><Upload /></el-icon>
        <span>上传卡片</span>
      </el-button>
    </header>

    <main class="community-main">
      <div class="community-content">
        <div class="community-toolbar">
          <el-radio-group
            :model-value="communityStore.filterType"
            @change="handleFilterChange"
          >
            <el-radio-button value="">
              全部
            </el-radio-button>
            <el-radio-button value="world">
              世界卡
            </el-radio-button>
            <el-radio-button value="character">
              人物卡
            </el-radio-button>
          </el-radio-group>
        </div>

        <div
          v-loading="communityStore.loading"
          class="community-list"
        >
          <el-empty
            v-if="!communityStore.loading && !communityStore.list.length"
            description="暂无卡片，快上传第一张吧！"
          />

          <div
            v-for="item in communityStore.list"
            :key="item.id"
            class="community-card"
            :class="{ expanded: communityStore.expandedId === item.id }"
          >
            <div
              class="card-row"
              @click="communityStore.toggleExpand(item.id)"
            >
              <div class="card-row-main">
                <div class="card-row-head">
                  <span class="card-name">{{ item.card_name }}</span>
                  <el-tag
                    size="small"
                    :type="item.card_type === 'world' ? 'primary' : 'success'"
                    effect="plain"
                  >
                    {{ item.card_type === 'world' ? '世界卡' : '人物卡' }}
                  </el-tag>
                </div>
                <div class="card-intro">
                  {{ item.intro || '暂无简介' }}
                </div>
              </div>
              <el-icon class="card-chevron">
                <ArrowDown v-if="communityStore.expandedId === item.id" />
                <ArrowRight v-else />
              </el-icon>
            </div>

            <div
              v-if="communityStore.expandedId === item.id"
              class="card-detail"
            >
              <div
                v-if="!isDetailReady(item.id)"
                class="detail-loading"
              >
                加载中...
              </div>
              <template v-else>
                <div class="detail-meta">
                  <span>上传者：{{ communityStore.currentDetail.poster_name || '匿名' }}</span>
                  <span class="meta-sep">|</span>
                  <span>来源：{{ communityStore.currentDetail.source_book_title || '未知' }}</span>
                  <span class="meta-sep">|</span>
                  <span>浏览：{{ communityStore.currentDetail.view_count || 0 }}</span>
                  <span class="meta-sep">|</span>
                  <span>时间：{{ formatDate(communityStore.currentDetail.created_at) }}</span>
                </div>

                <div class="detail-content">
                  <template v-if="communityStore.currentDetail.card_type === 'world'">
                    <pre class="detail-text">{{ communityStore.currentDetail.payload?.world_text || '（无内容）' }}</pre>
                  </template>
                  <template v-else-if="communityStore.currentDetail.card_type === 'character'">
                    <div class="char-fields">
                      <div class="char-field">
                        <span class="field-label">姓名</span>
                        <span class="field-value">{{ communityStore.currentDetail.payload?.name || '—' }}</span>
                      </div>
                      <div class="char-field">
                        <span class="field-label">角色</span>
                        <span class="field-value">{{ communityStore.currentDetail.payload?.role || '—' }}</span>
                      </div>
                    </div>
                    <pre class="detail-text">{{ communityStore.currentDetail.payload?.profile_text || '（无内容）' }}</pre>
                  </template>
                  <div
                    v-else
                    class="detail-unknown"
                  >
                    未知卡片类型
                  </div>
                </div>

                <div
                  v-if="canDelete"
                  class="detail-actions"
                >
                  <el-button
                    type="danger"
                    size="small"
                    @click="handleDelete(item.id)"
                  >
                    删除
                  </el-button>
                </div>
              </template>
            </div>
          </div>
        </div>

        <div
          v-if="communityStore.total > 0"
          class="community-pagination"
        >
          <el-pagination
            layout="prev, pager, next"
            :total="communityStore.total"
            :current-page="communityStore.page"
            :page-size="communityStore.pageSize"
            @current-change="handlePageChange"
          />
        </div>
      </div>
    </main>

    <UploadCardDialog
      v-model:visible="showUpload"
      @success="handleUploadSuccess"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { ArrowDown, ArrowLeft, ArrowRight, Upload } from '@element-plus/icons-vue';
import { useAuthStore } from '../../stores/auth';
import { useCommunityStore } from '../../stores/community';
import UploadCardDialog from './UploadCardDialog.vue';

const router = useRouter();
const auth = useAuthStore();
const communityStore = useCommunityStore();

const showUpload = ref(false);

const canDelete = computed(
  () =>
    auth.isLoggedIn &&
    !!communityStore.currentDetail &&
    communityStore.currentDetail.poster_user_id != null &&
    communityStore.currentDetail.poster_user_id === auth.user?.id,
);

function isDetailReady(itemId) {
  return (
    !!communityStore.currentDetail && communityStore.currentDetail.id === itemId
  );
}

function formatDate(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function backToWorkspace() {
  router.push(localStorage.getItem('lingshu_last_workspace_path') || '/workspace');
}

function handleFilterChange(value) {
  communityStore.setFilterType(value);
}

function handlePageChange(page) {
  communityStore.setPage(page);
}

async function handleDelete(postId) {
  try {
    await ElMessageBox.confirm('确认删除这张卡片？', '提示', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    });
  } catch {
    return;
  }
  try {
    await communityStore.deletePost(postId);
    ElMessage.success('已删除');
    communityStore.expandedId = null;
    await communityStore.fetchList();
  } catch (e) {
    ElMessage.error(e.message || '删除失败');
  }
}

async function handleUploadSuccess() {
  ElMessage.success('上传成功');
  await communityStore.setPage(1);
}

onMounted(() => {
  communityStore.fetchList();
});
</script>

<style scoped>
.community-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.community-topbar {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 56px;
  padding: 0 28px;
  border-bottom: 1px solid var(--border-light);
  background: color-mix(in srgb, var(--bg-primary) 92%, transparent);
  backdrop-filter: blur(10px);
}

.community-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.community-main {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.community-content {
  width: min(860px, calc(100% - 56px));
  margin: 0 auto;
  padding: 20px 0 64px;
}

.community-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  margin-bottom: 16px;
}

.community-list {
  min-height: 120px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.community-card {
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-primary);
  overflow: hidden;
  transition: border-color 0.2s;
}

.community-card:hover {
  border-color: var(--el-color-primary-light-5);
}

.community-card.expanded {
  border-color: var(--color-primary);
}

.card-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  cursor: pointer;
}

.card-row-main {
  flex: 1;
  min-width: 0;
}

.card-row-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.card-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-intro {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-chevron {
  flex-shrink: 0;
  color: var(--text-placeholder);
  font-size: 14px;
}

.card-detail {
  padding: 0 16px 16px;
  border-top: 1px solid var(--border-light);
  background: var(--bg-secondary);
}

.detail-loading {
  padding: 20px 0;
  text-align: center;
  color: var(--text-placeholder);
  font-size: 13px;
}

.detail-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 12px 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.meta-sep {
  color: var(--text-placeholder);
}

.detail-content {
  padding: 8px 0 12px;
}

.char-fields {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 24px;
  margin-bottom: 12px;
}

.char-field {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.field-label {
  font-size: 12px;
  color: var(--text-placeholder);
}

.field-value {
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 600;
}

.detail-text {
  margin: 0;
  padding: 12px 14px;
  border-radius: 6px;
  background: var(--bg-primary);
  border: 1px solid var(--border-light);
  color: var(--text-regular);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  max-height: 420px;
  overflow-y: auto;
}

.detail-unknown {
  padding: 16px 0;
  color: var(--text-placeholder);
  font-size: 13px;
  text-align: center;
}

.detail-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 8px;
}

.community-pagination {
  display: flex;
  justify-content: center;
  margin-top: 24px;
}

@media (max-width: 680px) {
  .community-topbar {
    padding: 0 14px;
  }

  .community-content {
    width: min(100% - 28px, 860px);
  }

  .detail-meta {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }

  .meta-sep {
    display: none;
  }
}
</style>
