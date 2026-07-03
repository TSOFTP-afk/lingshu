<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { ElMessage } from 'element-plus';
import { useBookstore } from '../stores/bookstore';
import type { BookSummary } from '../types';

interface ShelfBook extends BookSummary {
  author: string;
  genre: string;
  status: string;
  readLabel: string;
  popularity: string;
  coverTone: string;
  subTagList: string[];
}

const TAGS_MAP: Record<string, string[]> = JSON.parse(`{
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
  "诸天无限": ["无限流","原创副本","诸天流"]
}`);

const ALL_SUB_TAGS: string[] = Object.values(TAGS_MAP).flat();

const GENRE_SUFFIXES = [
  '热血冒险', '古典传承', '都市传奇', '史诗幻想', '星际文明',
  '武道巅峰', '魔幻世界', '王朝争霸', '悬疑探案', '温暖治愈',
];
const STATUSES = ['连载中', '连载中', '连载中', '新书', '完结'];
const READ_LABELS = ['免费试读', '立即阅读', '加入书箱', '免费阅读', '新书推荐'];
const COVER_TONES = ['red', 'ink', 'jade', 'navy', 'slate', 'amber', 'violet', 'cyan'];

const store = useBookstore();
const route = useRoute();
const selectedTags = ref<Set<string>>(new Set());
const expandedGender = ref('');
const expandedParent = ref('');
const randomSubTags = ref<string[]>([]);
const relatedSubTags = ref<string[]>([]);

const sharedTags = [
  '都市', '玄幻', '仙侠', '武侠', '科幻', '历史', '军事',
  '末世', '奇幻', '游戏', '体育', '诸天无限', '悬疑灵异',
  '轻小说', '二次元/同人', '现实', '文娱', '言情',
];

const genderCategories = [
  { name: '男频', children: sharedTags },
  { name: '女频', children: sharedTags },
];

const shelfBooks = computed<ShelfBook[]>(() =>
  store.books.map((book, index) => ({
    ...book,
    author: book.category === '本地上传' ? '本地作者' : '测试作者',
    genre: `${book.category} · ${GENRE_SUFFIXES[index % GENRE_SUFFIXES.length]}`,
    status: book.updated_at ? '连载中' : STATUSES[index % STATUSES.length],
    readLabel: READ_LABELS[index % READ_LABELS.length],
    popularity: (8 + ((index * 7 + 3) % 20) / 10).toFixed(1),
    coverTone: COVER_TONES[index % COVER_TONES.length],
    subTagList: book.sub_tags ? book.sub_tags.split(',').filter(Boolean) : [],
  })),
);

function pickRandom(arr: string[], count: number): string[] {
  const shuffled = [...arr].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, Math.min(count, shuffled.length));
}

function firstChar(title: string) {
  return title.slice(0, 1);
}

function formatCount(value: number) {
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万`;
  return String(value);
}

async function load() {
  try {
    const q = String(route.query.q || '');
    const params: { q?: string; category?: string } = { q };
    if (selectedTags.value.size > 0) {
      params.category = [...selectedTags.value].join(',');
    }
    await store.loadBooks(params);
  } catch {
    ElMessage.error('无法连接灵爻平台服务');
  }
}

function toggleGender(name: string) {
  if (expandedGender.value === name) {
    expandedGender.value = '';
    expandedParent.value = '';
    randomSubTags.value = [];
    relatedSubTags.value = [];
    return;
  }
  expandedGender.value = name;
  expandedParent.value = '';
  relatedSubTags.value = [];
  randomSubTags.value = pickRandom(ALL_SUB_TAGS, 20);
}

function showSubTags(parent: string) {
  if (expandedParent.value === parent) {
    expandedParent.value = '';
    relatedSubTags.value = [];
    return;
  }
  expandedParent.value = parent;
  relatedSubTags.value = pickRandom(TAGS_MAP[parent] || [], 20);
}

function clearTags() { selectedTags.value = new Set(); void load(); }
function toggleTag(tag: string) {
  const s = new Set(selectedTags.value);
  if (s.has(tag)) { s.delete(tag); } else { s.add(tag); }
  selectedTags.value = s;
  void load();
}

onMounted(() => {
  void load();
});

watch(() => route.query.q, () => {
  void load();
});
</script>

<template>
  <section class="bookstore-page">
    <div class="bookstore-container">
      <div class="bookstore-body">
        <aside class="category-sidebar">
          <h3 class="sidebar-title">全部分类</h3>
          <div
            v-for="group in genderCategories"
            :key="group.name"
            class="gender-group"
          >
            <button
              type="button"
              class="gender-toggle"
              :class="{ active: expandedGender === group.name }"
              @click="toggleGender(group.name)"
            >
              <span>{{ group.name }}</span>
              <i class="gender-arrow" :class="{ open: expandedGender === group.name }" />
            </button>
            <div v-show="expandedGender === group.name" class="tag-list">
              <div class="parent-tags-row">
                <button
                  v-for="tag in group.children"
                  :key="tag"
                  type="button"
                  class="parent-item"
                  :class="{ active: expandedParent === tag }"
                  @click="showSubTags(tag)"
                >
                  {{ tag }}
                </button>
              </div>

              <div v-if="expandedParent && relatedSubTags.length" class="sub-tag-area">
                <div class="sub-tag-label">{{ expandedParent }} · 相关标签</div>
                <div class="sub-tag-list">
                  <button
                    v-for="sub in relatedSubTags"
                    :key="sub"
                    type="button"
                    class="sub-item"
                    :class="{ active: selectedTags.has(sub) }"
                    @click="toggleTag(sub)"
                  >
                    {{ sub }}
                  </button>
                </div>
              </div>

              <div v-if="randomSubTags.length" class="sub-tag-area">
                <div class="sub-tag-label">随机推荐</div>
                <div class="sub-tag-list">
                  <button
                    v-for="sub in randomSubTags"
                    :key="sub"
                    type="button"
                    class="sub-item"
                    :class="{ active: selectedTags.has(sub) }"
                    @click="toggleTag(sub)"
                  >
                    {{ sub }}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </aside>

        <div class="bookstore-main">
          <div class="bookstore-stats">
            <span>共 {{ shelfBooks.length }} 本展示</span>
            <span v-if="selectedTags.size > 0" class="selected-cat">
              已选 {{ selectedTags.size }} 个标签
              <button type="button" class="clear-cat" @click="clearTags">×</button>
            </span>
          </div>

          <div v-loading="store.loading" class="book-shelf-grid">
            <RouterLink
              v-for="book in shelfBooks"
              :key="book.id"
              class="shelf-book"
              :to="`/books/${book.id}`"
            >
              <div class="book-cover" :class="book.coverTone">
                <img v-if="book.cover_url" :src="book.cover_url" :alt="book.title" />
                <span v-else>{{ firstChar(book.title) }}</span>
                <strong>{{ book.title }}</strong>
                <em>{{ book.category || '作品' }}</em>
              </div>
              <div class="shelf-info">
                <h3>{{ book.title }}</h3>
                <p>{{ book.summary }}</p>
                <div class="book-sub-tags" v-if="book.subTagList.length">
                  <span v-for="st in book.subTagList" :key="st" class="book-tag">{{ st }}</span>
                </div>
                <div class="shelf-meta">
                  <span>{{ book.author }}</span>
                  <span>{{ book.status }}</span>
                  <span>{{ formatCount(book.word_count) }}字</span>
                </div>
                <strong>{{ book.readLabel }}</strong>
              </div>
            </RouterLink>
          </div>

          <el-empty
            v-if="!store.loading && store.books.length === 0 && route.query.q"
            description="没有搜索到匹配的书籍"
          />
        </div>
      </div>
    </div>
  </section>
</template>
