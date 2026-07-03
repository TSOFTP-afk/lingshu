<template>
  <div class="chapter-tab-bar">
    <div
      ref="tabListRef"
      class="tab-list"
      :class="{ 'tab-list--dragging': isDragging }"
      @wheel.prevent="onWheel"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
      @pointerleave="onPointerLeave"
    >
      <TransitionGroup
        name="chapter-tab"
        tag="div"
        class="tab-track"
      >
        <div
          v-for="tab in tabs"
          :key="tab.key"
          class="tab-item"
          :class="{ 'tab-item--active': tab.key === activeKey, 'tab-item--dirty': tab.dirty }"
          :data-tab-key="tab.key"
        >
          <span class="tab-kind">{{ kindLabel(tab.kind) }}</span>
          <span class="tab-label">{{ tab.dirty ? '● ' : '' }}{{ tab.title }}</span>
          <span
            class="tab-close"
            @pointerdown.stop
            @click.stop="$emit('close', tab.key)"
          >&times;</span>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue';

const props = defineProps({
  tabs: { type: Array, default: () => [] },
  activeKey: { type: [String, null], default: null },
});

const emit = defineEmits(['activate', 'close']);
const tabListRef = ref(null);
const isDragging = ref(false);

let dragStartX = 0;
let dragStartScrollLeft = 0;
let dragMoved = false;
let pressedTabKey = null;

watch(
  () => [props.activeKey, props.tabs.length],
  () => nextTick(scrollActiveIntoView),
  { flush: 'post' },
);

function onWheel(event) {
  const el = tabListRef.value;
  if (!el) return;
  el.scrollLeft += Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY;
}

function onPointerDown(event) {
  const el = tabListRef.value;
  if (!el || event.button !== 0) return;
  const tabEl = event.target.closest?.('.tab-item');
  pressedTabKey = tabEl?.dataset?.tabKey || null;
  isDragging.value = true;
  dragMoved = false;
  dragStartX = event.clientX;
  dragStartScrollLeft = el.scrollLeft;
  el.setPointerCapture?.(event.pointerId);
}

function onPointerMove(event) {
  const el = tabListRef.value;
  if (!el || !isDragging.value) return;
  const dx = event.clientX - dragStartX;
  if (Math.abs(dx) > 4) dragMoved = true;
  el.scrollLeft = dragStartScrollLeft - dx;
}

function onPointerUp(event) {
  const el = tabListRef.value;
  const shouldActivate = pressedTabKey != null && !dragMoved;
  const tabKey = pressedTabKey;
  pressedTabKey = null;
  if (el?.hasPointerCapture?.(event.pointerId)) {
    el.releasePointerCapture(event.pointerId);
  }
  isDragging.value = false;
  if (dragMoved) {
    window.setTimeout(() => {
      dragMoved = false;
    }, 0);
    return;
  }
  if (shouldActivate) emit('activate', tabKey);
}

function onPointerLeave(event) {
  if (isDragging.value) onPointerUp(event);
}

function kindLabel(kind) {
  if (kind === 'book') return '书';
  if (kind === 'volume') return '卷';
  return '章';
}

function scrollActiveIntoView() {
  const el = tabListRef.value;
  if (!el || props.activeKey == null) return;
  const active = el.querySelector('.tab-item--active');
  active?.scrollIntoView({ behavior: 'smooth', inline: 'nearest', block: 'nearest' });
}
</script>

<style scoped>
.chapter-tab-bar {
  display: flex;
  align-items: center;
  height: 54px;
  padding: 7px 16px;
  background: linear-gradient(180deg, var(--bg-secondary), var(--bg-tertiary));
  border-bottom: 1px solid var(--border-color);
  overflow: hidden;
  flex-shrink: 0;
}

.tab-list {
  flex: 1;
  min-width: 0;
  height: 44px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  scrollbar-color: color-mix(in srgb, var(--color-primary) 34%, transparent) transparent;
  position: relative;
  cursor: grab;
  overscroll-behavior-x: contain;
  touch-action: pan-x;
}

.tab-list::-webkit-scrollbar {
  height: 6px;
}

.tab-list::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: color-mix(in srgb, var(--color-primary) 26%, transparent);
}

.tab-list::-webkit-scrollbar-track {
  background: transparent;
}

.tab-list--dragging {
  cursor: grabbing;
  user-select: none;
}

.tab-list--dragging .tab-item {
  cursor: grabbing;
}

.tab-track {
  display: flex;
  align-items: center;
  width: max-content;
  min-width: 100%;
  height: 38px;
}

.tab-item {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 286px;
  width: 286px;
  max-width: min(330px, 40vw);
  height: 36px;
  padding: 0 10px 0 12px;
  margin-right: 8px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(111, 80, 34, 0.06);
  cursor: pointer;
  font-size: var(--font-size-xs);
  white-space: nowrap;
  user-select: none;
  will-change: transform, opacity;
  transition:
    color var(--transition-fast),
    background var(--transition-fast),
    border-color var(--transition-fast),
    box-shadow var(--transition-fast),
    transform var(--transition-fast);
}

@media (max-width: 1280px) {
  .chapter-tab-bar {
    padding-left: 10px;
    padding-right: 10px;
  }

  .tab-item {
    flex-basis: 250px;
    width: 250px;
  }
}

.tab-item:hover {
  background: var(--bg-hover);
  transform: translateY(-1px);
  box-shadow: 0 5px 14px rgba(111, 80, 34, 0.10);
}

.tab-item--active {
  color: var(--color-primary);
  background: var(--bg-primary);
  border-color: color-mix(in srgb, var(--color-primary) 56%, var(--border-color));
  box-shadow:
    inset 0 0 0 1px color-mix(in srgb, var(--color-primary) 18%, transparent),
    0 6px 16px rgba(111, 80, 34, 0.12);
}

.tab-item--dirty .tab-label {
  color: var(--color-warning);
}

.tab-kind {
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  min-width: 24px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  color: var(--color-primary);
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-primary) 18%, transparent);
  font-size: 11px;
  font-weight: 700;
}

.tab-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tab-close {
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  width: 20px;
  height: 20px;
  margin-left: auto;
  border-radius: 999px;
  font-size: 14px;
  line-height: 1;
  opacity: 0.62;
  transition:
    opacity var(--transition-fast),
    background var(--transition-fast),
    transform var(--transition-fast);
}

.tab-close:hover {
  opacity: 1;
  background: var(--bg-hover);
  transform: rotate(90deg);
}

.chapter-tab-enter-active,
.chapter-tab-leave-active,
.chapter-tab-move {
  transition:
    opacity 180ms ease,
    transform 180ms ease,
    flex-basis 220ms ease,
    width 220ms ease,
    margin-right 220ms ease,
    padding 220ms ease;
}

.chapter-tab-enter-from,
.chapter-tab-leave-to {
  opacity: 0;
  transform: translateY(-8px) scale(0.96);
  flex-basis: 0;
  width: 0;
  margin-right: 0;
  padding-left: 0;
  padding-right: 0;
}

.chapter-tab-leave-active {
  pointer-events: none;
  overflow: hidden;
}
</style>
