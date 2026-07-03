<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  ArrowLeft,
  Collection,
  DataAnalysis,
  Document,
  DocumentAdd,
  DocumentChecked,
  EditPen,
  Grid,
  Tickets,
  UserFilled,
} from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import axios from 'axios';
import { useAuth } from '../stores/auth';

const auth = useAuth();
const route = useRoute();
const router = useRouter();

interface ProfileBook {
  id: number;
  title: string;
  summary: string;
  category: string;
  sub_tags: string;
  cover_url: string;
  chapter_count: number;
  word_count: number;
  latest_chapter_title: string | null;
  updated_at: string;
}

const books = ref<ProfileBook[]>([]);
const loading = ref(true);
const showCreateDialog = ref(false);
const creatingBook = ref(false);
const continuingWrite = ref(false);
const savingSummary = ref(false);
const summaryDraft = ref('');
const newBookForm = ref({
  title: '',
  sub_tags: '',
  summary: '',
});

// ---------- 作品标签编辑 ----------
const showTagDialog = ref(false);
const editingTags = ref<string[]>([]);
const tagSearchKeyword = ref('');

const TAGS_MAP: Record<string, string[]> = {
  "都市": ["创业","海岛","韩国","互联网","护花高手","金融","经营","美国","美洲","软饭流","商战","神豪","神医流","视频流","香港","医生流","战神流","直播文","职场","中医","赚钱"],
  "二次元/同人": ["动漫","红楼","精灵文","日本","水浒","特摄","西游","综漫","综武","崩坏学院","崩坏三","星铁","明日方舟","原神","终末地","绝区零","型月","碧蓝航线","碧蓝之海","鸣潮","战双","少年乐队","EVA","异环","咒回","战锤","春物","MC","火影","龙族","斗罗大陆","绝世唐门","龙王传说","终极斗罗","遮天","完美世界","圣墟","蔚蓝","鬼灭之刃","基金会","后室","奥特"],
  "军事": ["谍战","军工","军旅","抗战","特工","特种兵","战争","强国"],
  "科幻": ["机甲","基建流","基因","舰长","科技","科学家","赛博朋克","未来世界","星际","硬科幻","蒸汽朋克"],
  "历史": ["北宋","朝堂","崇祯","初唐","春秋战国","多子多福","工业","航海","洪武","皇帝流","嘉靖","架空历史","考据","科举","民国","明朝","谋略","南宋","女帝","女尊","秦朝","秦汉","清朝","权谋","三国","宋朝","唐朝","无穿越","五代十国","原始时代","贞观","中世纪","赘婿流","家族","争霸"],
  "末世": ["荒野","进化","末世","求生","丧尸"],
  "奇幻": ["DND","诡秘养成","剑与魔法","卡牌","克苏鲁","领主流","龙","魔法","魔女","欧洲","骑士","神话","神奇生物","巫师流","现代魔法","序列","学院流","异兽流","佣兵","御兽流","召唤流"],
  "轻小说": ["搞怪","搞笑","轻松","吐槽","玩梗","无节操"],
  "体育": ["NBA","篮球","足球"],
  "文娱": ["导演","港娱","歌手","韩娱","华娱","恋综","美娱","明星","偶像","日娱","文抄","文豪","文娱","相声演员","演员","综艺文"],
  "武侠": ["朝堂江湖","高武","国术","江湖","武道","练功"],
  "仙侠": ["白蛇","都市修仙","封神","古典修仙","洪荒","家族修仙","剑修","科技修真","儒道流","山海经","蜀山","现代修真","修仙","修真","长生","掌门流","阵法师","祖宗流","宗门"],
  "现实": ["宠物","打猎","非遗","非洲","警察","美食","民俗","奶爸文","年代文","日常文","三观正","乡村","校园","学霸文","学生","正能量","职业文","种田"],
  "玄幻": ["BOSS流","扮演流","扮猪吃虎","布局流","草根崛起","策略流","成神流","抽奖","创世流","词条","凡人流","反派","反套路","废柴流","分身","腹黑","苟道","极道流","加点流","谨慎","开挂流","开局流","快节奏","冷静","聊天群","灵气复苏","模拟器","幕后流","脑洞大","曝光流","气运流","签到","强者流","全民流","群像","热血","杀伐果断","设定党","升级流","熟练度","属性流","爽文","思路清奇","思想迪化","随身流","天才流","天幕流","无敌流","无金手指","无女主","无系统","系统流","心声","异能","智斗","智商在线","嘴炮","强者归来","重生","宗门"],
  "悬疑灵异": ["道士","诡异","诡异游戏","僵尸","聊斋","驱魔人","探案推理","探险","刑侦","玄学","悬疑流","志怪","捉鬼","规则怪谈"],
  "言情": ["爱情","单女主","多女主","婚姻无敌","恋爱","青梅","甜文","修罗场","治愈"],
  "游戏": ["LOL","NPC","第四天灾","电竞","玩家","网游","游戏现实","游戏异界","游戏制作"],
  "诸天无限": ["无限流","原创副本","诸天流"],
};

const ALL_SUB_TAGS: string[] = Object.values(TAGS_MAP).flat();

const availableTags = computed(() => {
  const kw = tagSearchKeyword.value.trim().toLowerCase();
  if (!kw) return ALL_SUB_TAGS;
  return ALL_SUB_TAGS.filter((t) => t.toLowerCase().includes(kw));
});

function toggleTag(tag: string) {
  const idx = editingTags.value.indexOf(tag);
  if (idx >= 0) {
    editingTags.value.splice(idx, 1);
  } else {
    editingTags.value.push(tag);
  }
}

function openTagDialog() {
  if (!selectedBook.value) return;
  editingTags.value = (selectedBook.value.sub_tags || '')
    .split(',')
    .map((t: string) => t.trim())
    .filter(Boolean);
  tagSearchKeyword.value = '';
  showTagDialog.value = true;
}

async function saveTags() {
  if (!selectedBook.value || !auth.token) return;
  try {
    const subTags = editingTags.value.join(',');
    const res = await axios.patch(`/api/author/books/${selectedBook.value.id}`, {
      sub_tags: subTags,
    }, { headers: authHeaders() });
    const item = res.data.item as ProfileBook;
    books.value = books.value.map((book) => (book.id === item.id ? { ...book, ...item } : book));
    showTagDialog.value = false;
    ElMessage.success('标签已更新');
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '标签更新失败');
  }
}

const selectedBookId = computed(() => {
  const raw = route.params.bookId;
  const value = Array.isArray(raw) ? raw[0] : raw;
  const id = Number(value);
  return Number.isFinite(id) && id > 0 ? id : null;
});
const isDetailMode = computed(() => selectedBookId.value !== null);
const selectedBook = computed(() =>
  books.value.find((book) => book.id === selectedBookId.value) || null,
);
const totalChapters = computed(() =>
  books.value.reduce((sum, book) => sum + Number(book.chapter_count || 0), 0),
);
const totalWords = computed(() =>
  books.value.reduce((sum, book) => sum + Number(book.word_count || 0), 0),
);
const hasSummaryChanges = computed(() =>
  Boolean(selectedBook.value) && summaryDraft.value !== (selectedBook.value?.summary || ''),
);

function formatWords(value: number): string {
  const n = Number(value || 0);
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return n.toLocaleString('zh-CN');
}

function firstChar(value: string): string {
  return value.trim().slice(0, 1) || '书';
}

function formatDate(value: string): string {
  if (!value) return '刚刚';
  return value.slice(0, 10);
}

function bookTags(book: ProfileBook): string[] {
  const tags = new Set<string>();
  const category = (book.category || '').trim();
  if (category && category !== '本地上传') tags.add(category);

  for (const tag of (book.sub_tags || '').split(',')) {
    const normalized = tag.trim();
    if (normalized) tags.add(normalized);
  }

  return tags.size > 0 ? [...tags] : ['自选'];
}

function openBook(bookId: number) {
  router.push(`/profile/books/${bookId}`);
}

function backToGallery() {
  router.push('/profile');
}

function openChapterManager(bookId: number) {
  router.push(`/profile/books/${bookId}/chapters`);
}

function authHeaders() {
  return { Authorization: `Bearer ${auth.token}` };
}

function openCreateBookDialog() {
  newBookForm.value = {
    title: '',
    sub_tags: '',
    summary: '',
  };
  showCreateDialog.value = true;
}

async function loadBooks() {
  if (!auth.token) {
    books.value = [];
    loading.value = false;
    return;
  }

  loading.value = true;
  try {
    const res = await axios.get('/api/author/books', {
      headers: { Authorization: `Bearer ${auth.token}` },
    });
    books.value = res.data.items || [];
  } catch {
    books.value = [];
  } finally {
    loading.value = false;
  }
}

async function createBook() {
  const title = newBookForm.value.title.trim();
  if (!title) {
    ElMessage.warning('请填写作品名称');
    return;
  }
  if (!auth.token) {
    auth.openLogin();
    return;
  }

  creatingBook.value = true;
  try {
    const res = await axios.post('/api/author/books', {
      title,
      sub_tags: newBookForm.value.sub_tags,
      summary: newBookForm.value.summary,
    }, {
      headers: authHeaders(),
    });
    const item = res.data.item as ProfileBook;
    showCreateDialog.value = false;
    ElMessage.success('作品已创建');
    await loadBooks();
    openBook(item.id);
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建作品失败');
  } finally {
    creatingBook.value = false;
  }
}

async function continueWriting() {
  if (!auth.token) {
    auth.openLogin();
    return;
  }
  if (books.value.length === 0) {
    openCreateBookDialog();
    return;
  }

  const target = books.value[0];
  continuingWrite.value = true;
  try {
    const res = await axios.post(`/api/author/books/${target.id}/chapters/next`, {}, {
      headers: authHeaders(),
    });
    const item = res.data.item as { id: number };
    ElMessage.success('已创建下一章草稿');
    await router.push(`/profile/books/${target.id}/chapters/${item.id}/edit`);
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '继续码字失败');
  } finally {
    continuingWrite.value = false;
  }
}

async function saveSummary() {
  if (!selectedBook.value) return;
  if (!auth.token) {
    auth.openLogin();
    return;
  }

  savingSummary.value = true;
  try {
    const res = await axios.patch(`/api/author/books/${selectedBook.value.id}`, {
      summary: summaryDraft.value,
    }, {
      headers: authHeaders(),
    });
    const item = res.data.item as ProfileBook;
    books.value = books.value.map((book) => (book.id === item.id ? { ...book, ...item } : book));
    summaryDraft.value = item.summary || '';
    ElMessage.success('作品简介已保存');
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败');
  } finally {
    savingSummary.value = false;
  }
}

onMounted(() => {
  void loadBooks();
});

watch(() => auth.token, () => {
  void loadBooks();
});

watch(
  [loading, selectedBookId, selectedBook],
  () => {
    if (!loading.value && selectedBookId.value !== null && !selectedBook.value) {
      void router.replace('/profile');
    }
  },
  { immediate: true },
);

watch(selectedBook, (book) => {
  summaryDraft.value = book?.summary || '';
}, { immediate: true });
</script>

<template>
  <div class="profile-page" :class="{ 'profile-page-detail': isDetailMode }">
    <div v-if="!auth.user" class="profile-login-hint">
      <el-empty description="请先登录以查看个人主页">
        <el-button type="primary" @click="auth.openLogin()">登录账号</el-button>
      </el-empty>
    </div>

    <template v-else>
      <section class="profile-hero">
        <div class="profile-hero-main">
          <el-avatar class="profile-avatar" :size="84" :icon="UserFilled" />
          <div class="profile-title">
            <span class="profile-eyebrow">作者工作台</span>
            <h1>{{ auth.user.username }}</h1>
            <p>{{ auth.user.is_author ? '管理作品、维护简介和查看创作数据' : '当前账号暂未开通作者权限' }}</p>
          </div>
        </div>

        <div class="profile-hero-actions">
          <el-tag :type="auth.user.is_author ? 'success' : 'info'" size="large">
            {{ auth.user.is_author ? '作者' : '读者' }}
          </el-tag>
          <el-button
            v-if="auth.user.is_author"
            type="primary"
            :icon="EditPen"
            :loading="continuingWrite"
            @click="continueWriting"
          >
            继续码字
          </el-button>
        </div>
      </section>

      <section v-if="auth.user.is_author" class="profile-stats" aria-label="作者统计">
        <article class="profile-stat">
          <span>作品</span>
          <strong>{{ books.length }}</strong>
          <small>已发布作品数</small>
        </article>
        <article class="profile-stat">
          <span>章节</span>
          <strong>{{ totalChapters }}</strong>
          <small>累计章节</small>
        </article>
        <article class="profile-stat">
          <span>总字数</span>
          <strong>{{ formatWords(totalWords) }}</strong>
          <small>全站展示字数</small>
        </article>
      </section>

      <el-empty
        v-if="!auth.user.is_author"
        class="profile-empty"
        description="当前账号不是作者账号"
      />

      <section v-else-if="!isDetailMode" class="profile-works">
        <div class="section-toolbar">
          <div>
            <span class="section-kicker">Works</span>
            <h2>我的作品</h2>
          </div>
          <el-button :icon="DocumentAdd" @click="openCreateBookDialog">新建作品</el-button>
        </div>

        <div v-if="!loading && books.length === 0" class="empty-work-card">
          <div class="empty-icon">
            <el-icon><DocumentAdd /></el-icon>
          </div>
          <h3>还没有发布过作品</h3>
          <p>从一个书名和一句简介开始，先把作品档案建起来，后续再慢慢补章节和数据。</p>
          <el-button type="primary" size="large" :icon="DocumentAdd" @click="openCreateBookDialog">
            发布你的第一个作品
          </el-button>
        </div>

        <div v-loading="loading" class="profile-book-grid" :class="{ empty: books.length === 0 }">
          <button
            v-for="book in books"
            :key="book.id"
            type="button"
            class="work-card"
            @click="openBook(book.id)"
          >
            <span class="work-cover">
              <img v-if="book.cover_url" :src="book.cover_url" :alt="book.title" />
              <span v-else>{{ firstChar(book.title) }}</span>
            </span>
            <span class="work-card-body">
              <span class="work-card-top">
                <strong>{{ book.title }}</strong>
                <small>{{ formatDate(book.updated_at) }}</small>
              </span>
              <span class="work-tags">
                <em v-for="tag in bookTags(book).slice(0, 3)" :key="tag">{{ tag }}</em>
              </span>
              <span class="work-summary">{{ book.summary || '暂无简介，进入作品管理后补充。' }}</span>
              <span class="work-meta">
                <span>{{ book.chapter_count }} 章</span>
                <span>{{ formatWords(book.word_count) }} 字</span>
                <span>管理</span>
              </span>
            </span>
          </button>
        </div>
      </section>

      <section v-else-if="selectedBook" class="profile-manager">
        <aside class="work-sidebar" aria-label="作品列表">
          <button type="button" class="sidebar-back" @click="backToGallery">
            <el-icon><ArrowLeft /></el-icon>
            <span>全部作品</span>
          </button>

          <div class="sidebar-title">
            <span>作品列表</span>
            <button type="button" @click="openCreateBookDialog">
              <el-icon><DocumentAdd /></el-icon>
            </button>
          </div>

          <button
            v-for="book in books"
            :key="book.id"
            type="button"
            class="sidebar-book"
            :class="{ active: book.id === selectedBook.id }"
            @click="openBook(book.id)"
          >
            <span class="sidebar-cover">
              <img v-if="book.cover_url" :src="book.cover_url" :alt="book.title" />
              <span v-else>{{ firstChar(book.title) }}</span>
            </span>
            <span class="sidebar-book-main">
              <strong>{{ book.title }}</strong>
              <small>{{ book.chapter_count }}章 · {{ formatWords(book.word_count) }}字</small>
            </span>
          </button>
        </aside>

        <article class="manager-panel">
          <section class="manager-hero-card">
            <div class="manager-cover">
              <img v-if="selectedBook.cover_url" :src="selectedBook.cover_url" :alt="selectedBook.title" />
              <span v-else>{{ firstChar(selectedBook.title) }}</span>
            </div>

            <div class="manager-main">
              <div class="manager-status-row">
                <span class="status-pill">连载中</span>
                <span>更新于 {{ formatDate(selectedBook.updated_at) }}</span>
              </div>
              <h2>{{ selectedBook.title }}</h2>
              <div class="manager-tags">
                <span v-for="tag in bookTags(selectedBook)" :key="tag">{{ tag }}</span>
              </div>

              <div class="manager-actions" aria-label="作品操作">
                <button type="button" class="action-co-create">
                  <el-icon><Collection /></el-icon>
                  <span>共创乐园</span>
                </button>
                <button type="button" class="action-chapters" @click="openChapterManager(selectedBook.id)">
                  <el-icon><Tickets /></el-icon>
                  <span>章节管理</span>
                </button>
                <button type="button" class="action-data">
                  <el-icon><DataAnalysis /></el-icon>
                  <span>书籍数据</span>
                </button>
                <button
                  type="button"
                  class="action-save"
                  :disabled="savingSummary || !hasSummaryChanges"
                  @click="saveSummary"
                >
                  <el-icon><DocumentChecked /></el-icon>
                  <span>{{ savingSummary ? '保存中' : '保存' }}</span>
                </button>
              </div>
            </div>
          </section>

          <section class="summary-editor-card">
            <div class="editor-heading">
              <div>
                <span>作品简介</span>
                <p>用于书库展示和作者后台管理。修改后点击上方“保存”。</p>
              </div>
              <small v-if="hasSummaryChanges">有未保存修改</small>
            </div>
            <el-input
              id="profile-summary-input"
              v-model="summaryDraft"
              class="profile-summary-input"
              type="textarea"
              resize="none"
              maxlength="4000"
              show-word-limit
              placeholder="写下这本书的简介..."
            />
          </section>

          <section v-if="selectedBook" class="profile-tags-card">
            <div class="editor-heading">
              <div>
                <span>作品标签</span>
                <p>标签用于书库分类和读者发现。点击"编辑标签"进行修改。</p>
              </div>
              <el-button type="primary" size="small" :icon="EditPen" @click="openTagDialog">编辑标签</el-button>
            </div>
            <div class="detail-tags">
              <span v-for="tag in bookTags(selectedBook)" :key="tag">{{ tag }}</span>
            </div>
          </section>

          <section class="manager-data-grid">
            <article>
              <el-icon><Document /></el-icon>
              <span>章节</span>
              <strong>{{ selectedBook.chapter_count }}</strong>
            </article>
            <article>
              <el-icon><Grid /></el-icon>
              <span>字数</span>
              <strong>{{ formatWords(selectedBook.word_count) }}</strong>
            </article>
            <article>
              <el-icon><Tickets /></el-icon>
              <span>最新章节</span>
              <strong>{{ selectedBook.latest_chapter_title || '暂无章节' }}</strong>
            </article>
          </section>
        </article>
      </section>

      <el-dialog
        v-if="auth.user.is_author"
        v-model="showCreateDialog"
        class="profile-create-dialog"
        title="新建作品"
        width="620px"
        :close-on-click-modal="false"
      >
        <div class="create-dialog-layout">
          <div class="create-preview">
            <span>{{ firstChar(newBookForm.title || '新书') }}</span>
            <strong>{{ newBookForm.title || '新作品' }}</strong>
            <small>{{ newBookForm.sub_tags || '标签稍后可补充' }}</small>
          </div>

          <el-form label-position="top" class="profile-create-form">
            <el-form-item label="作品名称">
              <el-input
                v-model="newBookForm.title"
                maxlength="100"
                show-word-limit
                placeholder="输入你的新作品名称"
                @keyup.enter="createBook"
              />
            </el-form-item>
            <el-form-item label="书籍标签">
              <el-input
                v-model="newBookForm.sub_tags"
                placeholder="例如：玄幻, 升级, 群像"
              />
            </el-form-item>
            <el-form-item label="作品简介">
              <el-input
                v-model="newBookForm.summary"
                type="textarea"
                resize="none"
                maxlength="4000"
                placeholder="先写一个简短介绍，之后可以在详情页继续修改"
                class="profile-create-summary"
              />
            </el-form-item>
          </el-form>
        </div>
        <template #footer>
          <div class="profile-dialog-footer">
            <el-button @click="showCreateDialog = false">取消</el-button>
            <el-button type="primary" :loading="creatingBook" :icon="DocumentAdd" @click="createBook">
              创建作品
            </el-button>
          </div>
        </template>
      </el-dialog>

      <el-dialog
        v-model="showTagDialog"
        title="编辑作品标签"
        width="620px"
        :close-on-click-modal="false"
        class="profile-tag-dialog"
      >
        <!-- 已选标签 -->
        <div class="detail-tags" v-if="editingTags.length" style="margin-bottom: 16px">
          <span
            v-for="tag in editingTags"
            :key="tag"
            class="tag-removable"
            @click="toggleTag(tag)"
          >{{ tag }} ✕</span>
        </div>
        <p v-else class="tag-empty-hint">点击下方标签进行添加</p>

        <!-- 标签搜索 -->
        <el-input
          v-model="tagSearchKeyword"
          placeholder="搜索标签..."
          clearable
          style="margin-bottom: 12px"
        />

        <!-- 备选标签池 -->
        <div class="tag-pool">
          <span
            v-for="tag in availableTags.slice(0, 80)"
            :key="tag"
            class="tag-candidate"
            :class="{ active: editingTags.includes(tag) }"
            @click="toggleTag(tag)"
          >{{ tag }}</span>
        </div>

        <template #footer>
          <div class="profile-dialog-footer">
            <el-button @click="showTagDialog = false">取消</el-button>
            <el-button type="primary" @click="saveTags">保存标签</el-button>
          </div>
        </template>
      </el-dialog>
    </template>
  </div>
</template>

<style scoped>
.profile-page {
  width: min(100% - 32px, 1120px);
  margin: 0 auto;
  padding: 34px 0 72px;
}

.profile-page-detail {
  width: min(100% - 28px, 1180px);
}

.profile-login-hint {
  padding-top: 80px;
}

.profile-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  min-height: 128px;
  margin-bottom: 18px;
  padding: 24px 28px;
  border: 1px solid rgba(184, 202, 216, 0.72);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.62);
  box-shadow: 0 12px 32px rgba(26, 45, 61, 0.08);
}

.profile-hero-main {
  display: flex;
  align-items: center;
  gap: 20px;
  min-width: 0;
}

.profile-avatar {
  flex: 0 0 auto;
  background: linear-gradient(135deg, #B9C5D2, #A9B4C3);
  color: #fff;
}

.profile-title {
  min-width: 0;
}

.profile-eyebrow,
.section-kicker {
  color: #2F86B6;
  font-size: 12px;
  font-weight: 850;
  letter-spacing: 0;
}

.profile-title h1 {
  margin: 6px 0 8px;
  color: #12283A;
  font-size: 34px;
  font-weight: 900;
  line-height: 1.05;
}

.profile-title p {
  margin: 0;
  color: #5E7487;
  font-size: 14px;
}

.profile-hero-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 12px;
}

.profile-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 34px;
}

.profile-stat {
  min-width: 0;
  padding: 18px 20px;
  border: 1px solid rgba(184, 202, 216, 0.72);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 8px 24px rgba(26, 45, 61, 0.06);
}

.profile-stat span,
.profile-stat small {
  display: block;
  color: #6E8395;
  font-size: 13px;
  font-weight: 700;
}

.profile-stat strong {
  display: block;
  margin: 8px 0 6px;
  color: #2F86B6;
  font-size: 30px;
  font-weight: 900;
  line-height: 1;
}

.profile-empty {
  padding-top: 32px;
}

.section-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.section-toolbar h2 {
  margin: 4px 0 0;
  color: #12283A;
  font-size: 24px;
  font-weight: 900;
}

.empty-work-card {
  display: grid;
  place-items: center;
  min-height: 360px;
  padding: 42px 24px;
  border: 1px dashed rgba(47, 134, 182, 0.36);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.48);
  text-align: center;
}

.empty-icon {
  display: grid;
  width: 74px;
  height: 74px;
  place-items: center;
  margin-bottom: 18px;
  border-radius: 8px;
  color: #2F86B6;
  background: rgba(47, 134, 182, 0.12);
  font-size: 34px;
}

.empty-work-card h3 {
  margin: 0 0 10px;
  color: #12283A;
  font-size: 22px;
  font-weight: 900;
}

.empty-work-card p {
  width: min(100%, 430px);
  margin: 0 0 24px;
  color: #5E7487;
  font-size: 14px;
  line-height: 1.8;
}

.profile-book-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(252px, 1fr));
  gap: 16px;
  min-height: 120px;
}

.profile-book-grid.empty {
  display: block;
  min-height: 0;
}

.work-card {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 14px;
  min-width: 0;
  padding: 14px;
  border: 1px solid rgba(184, 202, 216, 0.78);
  border-radius: 8px;
  color: inherit;
  background: rgba(255, 255, 255, 0.74);
  box-shadow: 0 8px 20px rgba(26, 45, 61, 0.06);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.18s, box-shadow 0.18s, transform 0.18s;
}

.work-card:hover,
.work-card:focus-visible {
  border-color: rgba(47, 134, 182, 0.5);
  box-shadow: 0 12px 28px rgba(26, 45, 61, 0.1);
  transform: translateY(-2px);
}

.work-cover,
.sidebar-cover,
.manager-cover,
.create-preview {
  display: grid;
  place-items: center;
  overflow: hidden;
  border-radius: 6px;
  background:
    linear-gradient(160deg, rgba(47, 134, 182, 0.18), rgba(119, 220, 204, 0.2)),
    #EAF4FA;
}

.work-cover {
  width: 76px;
  aspect-ratio: 3 / 4;
}

.work-cover img,
.sidebar-cover img,
.manager-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.work-cover > span,
.sidebar-cover > span,
.manager-cover > span {
  color: #2F86B6;
  font-size: 28px;
  font-weight: 900;
}

.work-card-body,
.sidebar-book-main {
  min-width: 0;
}

.work-card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.work-card-top strong {
  overflow: hidden;
  color: #12283A;
  font-size: 16px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.work-card-top small,
.work-summary,
.work-meta,
.sidebar-book-main small {
  color: #6E8395;
  font-size: 12px;
}

.work-tags,
.manager-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.work-tags em,
.manager-tags span {
  display: inline-flex;
  min-height: 22px;
  align-items: center;
  padding: 0 8px;
  border-radius: 999px;
  color: #1A6F99;
  background: rgba(47, 134, 182, 0.1);
  font-size: 12px;
  font-style: normal;
  font-weight: 800;
}

.work-summary {
  display: -webkit-box;
  min-height: 38px;
  margin-top: 10px;
  overflow: hidden;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.work-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
  font-weight: 800;
}

.profile-manager {
  display: grid;
  grid-template-columns: 256px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.work-sidebar {
  position: sticky;
  top: 92px;
  display: grid;
  gap: 10px;
  max-height: calc(100vh - 112px);
  padding: 12px;
  border: 1px solid rgba(184, 202, 216, 0.72);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.68);
  box-shadow: 0 8px 24px rgba(26, 45, 61, 0.06);
  overflow: auto;
}

.sidebar-back,
.sidebar-book,
.sidebar-title button,
.manager-actions button {
  border: 0;
  font-family: inherit;
}

.sidebar-back {
  display: inline-flex;
  height: 38px;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border-radius: 6px;
  color: #2F86B6;
  background: rgba(47, 134, 182, 0.1);
  cursor: pointer;
  font-weight: 850;
}

.sidebar-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 4px 0;
  color: #5E7487;
  font-size: 12px;
  font-weight: 900;
}

.sidebar-title button {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 6px;
  color: #2F86B6;
  background: transparent;
  cursor: pointer;
}

.sidebar-title button:hover {
  background: rgba(47, 134, 182, 0.1);
}

.sidebar-book {
  display: grid;
  grid-template-columns: 46px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  padding: 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: inherit;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.sidebar-book:hover,
.sidebar-book.active {
  border-color: rgba(47, 134, 182, 0.3);
  background: rgba(47, 134, 182, 0.1);
}

.sidebar-cover {
  width: 46px;
  aspect-ratio: 3 / 4;
}

.sidebar-cover > span {
  font-size: 18px;
}

.sidebar-book-main strong,
.sidebar-book-main small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-book-main strong {
  color: #12283A;
  font-size: 14px;
  font-weight: 900;
}

.sidebar-book-main small {
  margin-top: 4px;
}

.manager-panel {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.manager-hero-card,
.summary-editor-card,
.profile-tags-card,
.manager-data-grid article {
  border: 1px solid rgba(184, 202, 216, 0.72);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 10px 28px rgba(26, 45, 61, 0.07);
}

.manager-hero-card {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 22px;
  padding: 20px;
}

.manager-cover {
  aspect-ratio: 3 / 4;
}

.manager-cover > span {
  font-size: 46px;
}

.manager-main {
  min-width: 0;
}

.manager-status-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  color: #6E8395;
  font-size: 13px;
}

.status-pill {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  padding: 0 10px;
  border-radius: 999px;
  color: #1F7A55;
  background: rgba(84, 214, 148, 0.16);
  font-weight: 850;
}

.manager-main h2 {
  margin: 12px 0 0;
  color: #12283A;
  font-size: 30px;
  font-weight: 900;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.manager-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 22px;
}

.manager-actions button {
  display: inline-flex;
  min-width: 118px;
  height: 36px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 14px;
  border-radius: 6px;
  color: #12283A;
  cursor: default;
  font-size: 14px;
  font-weight: 900;
}

.action-co-create {
  background: linear-gradient(90deg, #57A9DB, #7BE1D1);
}

.action-chapters {
  background: #B9DCF0;
}

.manager-actions .action-chapters {
  cursor: pointer;
  transition: filter 0.18s, transform 0.18s;
}

.action-chapters:hover {
  filter: brightness(0.98);
  transform: translateY(-1px);
}

.action-data {
  background: #A9ECE2;
}

.action-save {
  background: #DDF5C8;
  transition: filter 0.18s, transform 0.18s;
}

.manager-actions .action-save {
  cursor: pointer;
}

.action-save:hover:not(:disabled) {
  filter: brightness(0.98);
  transform: translateY(-1px);
}

.action-save:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.summary-editor-card,
.profile-tags-card {
  padding: 18px;
}

.editor-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.editor-heading span {
  color: #12283A;
  font-size: 18px;
  font-weight: 900;
}

.editor-heading p {
  margin: 4px 0 0;
  color: #6E8395;
  font-size: 13px;
}

.editor-heading small {
  flex: 0 0 auto;
  color: #2F86B6;
  font-size: 12px;
  font-weight: 850;
}

.profile-summary-input :deep(.el-textarea__inner) {
  min-height: 160px !important;
  padding: 12px 14px;
  border: 1px solid rgba(184, 202, 216, 0.9);
  border-radius: 8px;
  color: #263847;
  background: rgba(248, 251, 253, 0.8);
  box-shadow: none;
  font-size: 15px;
  line-height: 1.8;
}

.profile-summary-input :deep(.el-textarea__inner:focus) {
  border-color: rgba(47, 134, 182, 0.58);
  box-shadow: 0 0 0 3px rgba(47, 134, 182, 0.12);
}

.manager-data-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.manager-data-grid article {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 16px;
}

.manager-data-grid .el-icon {
  color: #2F86B6;
  font-size: 20px;
}

.manager-data-grid span {
  color: #6E8395;
  font-size: 13px;
  font-weight: 800;
}

.manager-data-grid strong {
  overflow: hidden;
  color: #12283A;
  font-size: 18px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-create-dialog :deep(.el-dialog) {
  border-radius: 8px;
  background: #F8FBFD;
}

.profile-create-dialog :deep(.el-dialog__header) {
  padding: 22px 24px 8px;
}

.profile-create-dialog :deep(.el-dialog__title) {
  color: #12283A;
  font-size: 20px;
  font-weight: 900;
}

.create-dialog-layout {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.create-preview {
  aspect-ratio: 3 / 4.35;
  padding: 18px;
  text-align: center;
}

.create-preview span {
  color: #2F86B6;
  font-size: 42px;
  font-weight: 900;
}

.create-preview strong,
.create-preview small {
  display: block;
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.create-preview strong {
  margin-top: auto;
  color: #12283A;
  font-size: 16px;
  font-weight: 900;
  white-space: nowrap;
}

.create-preview small {
  color: #6E8395;
  font-size: 12px;
}

.profile-create-form :deep(.el-form-item__label) {
  color: #12283A;
  font-weight: 850;
}

.profile-create-summary :deep(.el-textarea__inner) {
  min-height: 132px !important;
  line-height: 1.7;
}

.profile-dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

@media (max-width: 920px) {
  .profile-manager {
    grid-template-columns: 1fr;
  }

  .work-sidebar {
    position: static;
    grid-auto-flow: column;
    grid-auto-columns: minmax(180px, 1fr);
    max-height: none;
    overflow-x: auto;
  }

  .sidebar-back {
    height: auto;
    min-height: 62px;
  }
}

@media (max-width: 720px) {
  .profile-page {
    width: min(100% - 24px, 1120px);
    padding-top: 24px;
  }

  .profile-hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .profile-hero-actions {
    width: 100%;
    justify-content: space-between;
  }

  .profile-title h1 {
    font-size: 28px;
  }

  .profile-stats,
  .manager-data-grid {
    grid-template-columns: 1fr;
  }

  .section-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .manager-hero-card,
  .create-dialog-layout {
    grid-template-columns: 1fr;
  }

  .manager-cover,
  .create-preview {
    width: min(180px, 60vw);
  }
}

@media (max-width: 520px) {
  .profile-hero-main {
    align-items: flex-start;
    width: 100%;
  }

  .profile-avatar {
    --el-avatar-size: 64px !important;
  }

  .profile-hero-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .profile-hero-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }

  .profile-book-grid {
    grid-template-columns: 1fr;
  }

  .work-card {
    grid-template-columns: 64px minmax(0, 1fr);
  }

  .work-cover {
    width: 64px;
  }

  .manager-actions button {
    flex: 1 1 140px;
  }

  .manager-actions {
    display: grid;
    grid-template-columns: 1fr;
  }

  .manager-actions button {
    width: 100%;
  }
}

/* ---------- 标签编辑弹窗 ---------- */
.tag-removable {
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.tag-removable:hover {
  background: rgba(231, 76, 60, 0.12);
  border-color: #e74c3c;
  color: #c0392b;
}

.tag-empty-hint {
  margin: 0 0 16px;
  color: #a3bcd0;
  font-size: 13px;
}

.tag-pool {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 280px;
  overflow-y: auto;
  padding: 12px;
  border: 1px solid #d6e3ef;
  border-radius: 6px;
  background: #f6fafd;
}

.tag-candidate {
  height: 26px;
  padding: 2px 10px;
  border: 1px solid #d0dde8;
  border-radius: 4px;
  color: #4a6d84;
  background: #fff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  display: inline-flex;
  align-items: center;
  user-select: none;
}

.tag-candidate:hover {
  border-color: #2F86B6;
  color: #1A6F99;
  background: rgba(47, 134, 182, 0.08);
}

.tag-candidate.active {
  border-color: #2F86B6;
  color: #fff;
  background: #2F86B6;
}
</style>
