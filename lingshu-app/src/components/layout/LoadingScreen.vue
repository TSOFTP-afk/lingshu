<template>
  <div class="loading-screen">
    <div class="loading-content">
      <div class="brand">
        <span class="brand-logo">灵枢</span>
        <span class="brand-sub">智能写作工作台</span>
      </div>

      <div class="progress-wrapper">
        <div class="progress-bar">
          <div
            class="progress-fill"
            :style="{ width: percent + '%' }"
          />
        </div>
        <p class="progress-text">
          {{ message }}
        </p>
      </div>

      <div class="loading-dots">
        <span
          v-for="i in 3"
          :key="i"
          class="dot"
          :style="{ animationDelay: (i * 0.2) + 's' }"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';

const percent = ref(0);
const message = ref('正在启动灵枢...');

const stages = [
  { pct: 20, msg: '检查后端服务...' },
  { pct: 40, msg: '加载 AI 模型配置...' },
  { pct: 60, msg: '初始化工作台...' },
  { pct: 80, msg: '准备编辑器...' },
  { pct: 100, msg: '就绪' },
];

onMounted(async () => {
  // 模拟启动进度
  for (const stage of stages) {
    await new Promise(r => setTimeout(r, 400));
    percent.value = stage.pct;
    message.value = stage.msg;
  }
  // 启动完成后由父组件控制隐藏
  setTimeout(() => emit('ready'), 300);
});

const emit = defineEmits(['ready']);
</script>

<style scoped>
.loading-screen {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  display: flex;
  align-items: center;
  justify-content: center;
}
.loading-content {
  text-align: center;
  color: #e0e0e0;
}
.brand {
  margin-bottom: 40px;
}
.brand-logo {
  display: block;
  font-size: 48px;
  font-weight: 700;
  color: #6c8cff;
  letter-spacing: 8px;
  text-shadow: 0 0 30px rgba(108, 140, 255, 0.4);
}
.brand-sub {
  display: block;
  font-size: 14px;
  color: #9090b0;
  margin-top: 8px;
  letter-spacing: 4px;
}
.progress-wrapper {
  width: 280px;
  margin: 0 auto;
}
.progress-bar {
  height: 3px;
  background: rgba(255,255,255,0.1);
  border-radius: 2px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #6c8cff, #a0cfff);
  border-radius: 2px;
  transition: width 0.5s ease;
}
.progress-text {
  font-size: 12px;
  color: #9090b0;
  margin-top: 10px;
}
.loading-dots {
  margin-top: 24px;
  display: flex;
  justify-content: center;
  gap: 8px;
}
.dot {
  width: 6px;
  height: 6px;
  background: #6c8cff;
  border-radius: 50%;
  animation: pulse 1.2s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 0.2; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.3); }
}
</style>
