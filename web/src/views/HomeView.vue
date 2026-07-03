<script setup lang="ts">
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  EditPen,
  Search,
  TrendCharts,
} from '@element-plus/icons-vue';

const router = useRouter();
const keyword = ref('');

const topicCards = [
  { title: '读者热议', desc: '章节讨论、角色投票、世界观补完等社区内容。', icon: TrendCharts },
  { title: '创作挑战', desc: '短篇命题、世界共创和作者冲榜活动预留入口。', icon: EditPen },
];

const forumPosts = [
  { tag: '书评', title: '本地上传章节如何做成连续追更体验？', meta: '128 回复 · 2.4k 浏览' },
  { tag: '推荐', title: '近期值得补的都市幻想与轻小说设定', meta: '86 回复 · 1.8k 浏览' },
  { tag: '共创', title: '开放一个"镜湖城"世界观接龙专区', meta: '42 回复 · 980 浏览' },
];

const hotTags = ['玄幻', '都市脑洞', '轻小说', '悬疑', '机甲', '群像', '经营', '古典仙侠'];

function runSearch() {
  const q = keyword.value.trim();
  router.push({ path: '/bookstore', query: q ? { q } : {} });
}
</script>

<template>
  <section class="home-page">
    <div class="home-container">
      <div class="home-search-bar">
        <el-input
          v-model="keyword"
          :prefix-icon="Search"
          clearable
          size="large"
          placeholder="搜索书名、简介或分类"
          @keyup.enter="runSearch"
          @clear="runSearch"
        />
        <el-button type="primary" size="large" @click="runSearch">搜索</el-button>
      </div>

      <div class="home-marquee">
        <strong>今日看点</strong>
        <span>本地上传作品优先展示，适合演示从灵枢工具发布到灵爻平台的闭环。</span>
        <div class="hot-tags">
          <button v-for="tag in hotTags" :key="tag" type="button">{{ tag }}</button>
        </div>
      </div>

      <aside class="topic-column">
        <section class="topic-card">
          <div class="panel-heading">
            <h2>专题与活动</h2>
            <span>平台运营</span>
          </div>
          <article v-for="topic in topicCards" :key="topic.title" class="topic-row">
            <div class="topic-icon">
              <component :is="topic.icon" />
            </div>
            <div>
              <h3>{{ topic.title }}</h3>
              <p>{{ topic.desc }}</p>
            </div>
          </article>
        </section>

        <section class="forum-card">
          <div class="panel-heading">
            <h2>读者讨论</h2>
            <span>社区</span>
          </div>
          <article v-for="post in forumPosts" :key="post.title" class="forum-row">
            <span>{{ post.tag }}</span>
            <div>
              <h3>{{ post.title }}</h3>
              <p>{{ post.meta }}</p>
            </div>
          </article>
        </section>
      </aside>
    </div>
  </section>
</template>
