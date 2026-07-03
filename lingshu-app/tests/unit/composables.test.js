import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ref, nextTick } from 'vue';
import { useAutoSave, useWordCount } from '../../src/composables/useAutoSave';

// ---------------------------------------------------------------------------
// Helper: 在 Vue 组件上下文中执行 composable（让 onUnmounted 等生命周期钩子生效）
// ---------------------------------------------------------------------------
function withSetup(composableFn) {
  let result;
  const unmountFns = [];

  // 使用 Vue 的 mount/unmount 生命周期模拟
  const { mount, unmount } = require('@vue/test-utils');
  // 简易方案：直接在 setup 中调用
  const TestComponent = {
    setup() {
      result = composableFn();
      return () => {}; // render fn
    },
  };

  // 我们不真正挂载 DOM，而是利用 Vue 的 createApp + unmount 来驱动生命周期
  const { createApp, h } = require('vue');
  const app = createApp(TestComponent);
  const doc = document.createElement('div');
  app.mount(doc);

  const unmountApp = () => app.unmount();
  return { result, unmount: unmountApp };
}

// ===========================================================================
// useAutoSave
// ===========================================================================
describe('useAutoSave', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('markDirty 将 dirty 设为 true', () => {
    const saveFn = vi.fn();
    const { result } = withSetup(() => useAutoSave(saveFn));
    expect(result.dirty.value).toBe(false);
    result.markDirty();
    expect(result.dirty.value).toBe(true);
  });

  it('markClean 将 dirty 设为 false 并更新 lastSaved', () => {
    const saveFn = vi.fn();
    const { result } = withSetup(() => useAutoSave(saveFn));
    result.markDirty();
    expect(result.dirty.value).toBe(true);

    const before = new Date();
    result.markClean();
    const after = new Date();

    expect(result.dirty.value).toBe(false);
    expect(result.lastSaved.value).toBeInstanceOf(Date);
    expect(result.lastSaved.value.getTime()).toBeGreaterThanOrEqual(before.getTime());
    expect(result.lastSaved.value.getTime()).toBeLessThanOrEqual(after.getTime());
  });

  it('save() 在 dirty 时调用 saveFn', async () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { result } = withSetup(() => useAutoSave(saveFn));
    result.markDirty();
    await result.save();
    expect(saveFn).toHaveBeenCalledTimes(1);
    expect(result.dirty.value).toBe(false);
    expect(result.saving.value).toBe(false);
  });

  it('save() 在非 dirty 时不会调用 saveFn', async () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { result } = withSetup(() => useAutoSave(saveFn));
    // dirty 为 false（默认值）
    await result.save();
    expect(saveFn).not.toHaveBeenCalled();
  });

  it('save() 在 saving 时不会重复调用 saveFn', async () => {
    let resolveSave;
    const saveFn = vi.fn().mockImplementation(() => new Promise((r) => { resolveSave = r; }));
    const { result } = withSetup(() => useAutoSave(saveFn));
    result.markDirty();

    // 第一次 save，尚未完成
    const savePromise = result.save();
    expect(result.saving.value).toBe(true);

    // 在 saving 期间再次调用 save
    await result.save();
    // 此时 saveFn 应该只被调用了一次
    expect(saveFn).toHaveBeenCalledTimes(1);

    // 完成第一次 save
    resolveSave();
    await savePromise;
    expect(result.saving.value).toBe(false);
  });

  it('scheduleAutoSave 在 interval 后触发 save', async () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { result } = withSetup(() => useAutoSave(saveFn, { interval: 2000 }));
    result.markDirty();
    result.scheduleAutoSave();

    // 还没到时间
    vi.advanceTimersByTime(1999);
    expect(saveFn).not.toHaveBeenCalled();

    // 到时间了
    vi.advanceTimersByTime(1);
    await nextTick();
    // 等待 async save 完成
    await vi.runAllTimersAsync();
    expect(saveFn).toHaveBeenCalledTimes(1);
  });

  it('scheduleAutoSave 在 enabled=false 时不调度', () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { result } = withSetup(() => useAutoSave(saveFn, { enabled: false, interval: 1000 }));
    result.markDirty();
    result.scheduleAutoSave();

    vi.advanceTimersByTime(5000);
    expect(saveFn).not.toHaveBeenCalled();
  });

  it('scheduleAutoSave 在非 dirty 时不调度', () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { result } = withSetup(() => useAutoSave(saveFn, { interval: 1000 }));
    // dirty 为 false
    result.scheduleAutoSave();

    vi.advanceTimersByTime(5000);
    expect(saveFn).not.toHaveBeenCalled();
  });

  it('scheduleAutoSave 清除之前的定时器（防抖）', () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { result } = withSetup(() => useAutoSave(saveFn, { interval: 2000 }));
    result.markDirty();

    // 连续调度两次
    result.scheduleAutoSave();
    vi.advanceTimersByTime(1000);
    result.scheduleAutoSave();

    // 第一个定时器的时间已过，但被清除了
    vi.advanceTimersByTime(1000);
    // 还没到第二个定时器的时间
    expect(saveFn).not.toHaveBeenCalled();

    // 再过 1000ms，第二个定时器触发
    vi.advanceTimersByTime(1000);
    expect(saveFn).toHaveBeenCalledTimes(1);
  });

  it('onUnmounted 清除定时器', () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { result, unmount } = withSetup(() => useAutoSave(saveFn, { interval: 2000 }));
    result.markDirty();
    result.scheduleAutoSave();

    // 卸载组件
    unmount();

    // 时间到了也不应该触发
    vi.advanceTimersByTime(5000);
    expect(saveFn).not.toHaveBeenCalled();
  });

  it('save() 完成后调用 markClean', async () => {
    const saveFn = vi.fn().mockResolvedValue(undefined);
    const { result } = withSetup(() => useAutoSave(saveFn));
    result.markDirty();
    await result.save();
    expect(result.dirty.value).toBe(false);
    expect(result.lastSaved.value).toBeInstanceOf(Date);
  });

  it('save() 即使 saveFn 抛出异常也重置 saving', async () => {
    const saveFn = vi.fn().mockRejectedValue(new Error('保存失败'));
    const { result } = withSetup(() => useAutoSave(saveFn));
    result.markDirty();
    await expect(result.save()).rejects.toThrow('保存失败');
    expect(result.saving.value).toBe(false);
    // 出错时 dirty 仍为 true（markClean 未被调用）
    expect(result.dirty.value).toBe(true);
  });
});

// ===========================================================================
// useWordCount
// ===========================================================================
describe('useWordCount', () => {
  it('空字符串返回 0', () => {
    const textRef = ref('');
    const { wordCount } = useWordCount(textRef);
    expect(wordCount.value).toBe(0);
  });

  it('"hello world" 返回 10（去除空格）', () => {
    const textRef = ref('hello world');
    const { wordCount } = useWordCount(textRef);
    expect(wordCount.value).toBe(10);
  });

  it('中文文本 "你好世界" 返回 4', () => {
    const textRef = ref('你好世界');
    const { wordCount } = useWordCount(textRef);
    expect(wordCount.value).toBe(4);
  });

  it('包含空白字符的文本正确计数', () => {
    const textRef = ref('a b\tc\nd');
    const { wordCount } = useWordCount(textRef);
    expect(wordCount.value).toBe(4);
  });

  it('响应式：修改 textRef 后 wordCount 更新', async () => {
    const textRef = ref('hello');
    const { wordCount } = useWordCount(textRef);
    expect(wordCount.value).toBe(5);

    textRef.value = '你好世界';
    await nextTick();
    expect(wordCount.value).toBe(4);
  });

  it('textRef 为 undefined/null 时安全处理', () => {
    const textRef = ref(null);
    const { wordCount } = useWordCount(textRef);
    expect(wordCount.value).toBe(0);
  });
});
