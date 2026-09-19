import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus, { ElMessageBox } from 'element-plus';
import AnalysisTab from '../../../src/components/drawer/AnalysisTab.vue';
import { useBookStore } from '../../../src/stores/book';
import { useAuthStore } from '../../../src/stores/auth';
import api from '../../../src/utils/api';
import { __mockBusState as eventBusState } from '../../../src/composables/useEventBus';

// ---------------------------------------------------------------------------
// mock: eventBus（组件通过它对外发 characters-updated / world-updated /
// book-updated / writeback-completed / drawer-tab，并监听 book-analysis-start）
// 状态放在工厂内部并通过 __mockBusState 导出，避免 hoisting TDZ 问题。
// ---------------------------------------------------------------------------

vi.mock('../../../src/composables/useEventBus', () => {
  const state = { handlers: {}, emitted: [] };
  return {
    __mockBusState: state,
    useEventBus: () => ({
      on: (event, cb) => {
        (state.handlers[event] ||= []).push(cb);
      },
      off: (event, cb) => {
        state.handlers[event] = (state.handlers[event] || []).filter((item) => item !== cb);
      },
      emit: (event, payload) => {
        state.emitted.push({ event, payload });
        (state.handlers[event] || []).forEach((cb) => cb(payload));
      },
    }),
  };
});

// ---------------------------------------------------------------------------
// mock: src/utils/api（组件 30 处 api.* 调用全部可控 + buildWsUrl/sendWsAuth）
// vi.fn 实例在工厂内创建，测试里通过 import 拿到的就是同一份 mock。
// ---------------------------------------------------------------------------

vi.mock('../../../src/utils/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  getAuthToken: vi.fn(() => 'test-token'),
  setAuthToken: vi.fn(),
  tokenReady: Promise.resolve(),
  buildWsUrl: vi.fn((path) => `ws://mock.test${path}`),
  sendWsAuth: vi.fn((ws) => {
    ws.send(JSON.stringify({ type: 'auth', payload: { token: 'test-token' } }));
    return 'test-token';
  }),
}));

// ---------------------------------------------------------------------------
// mock: global.WebSocket（记录实例、send、监听器，可手动触发 open/message）
// ---------------------------------------------------------------------------
class MockWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    this.closed = false;
    this.listeners = {};
    this.onopen = null;
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;
    this._setIntentionalClose = null;
    MockWebSocket.instances.push(this);
  }

  static instances = [];
  static OPEN = 1;

  send(data) {
    this.sent.push(JSON.parse(data));
  }

  addEventListener(type, cb) {
    (this.listeners[type] ||= []).push(cb);
  }

  removeEventListener(type, cb) {
    this.listeners[type] = (this.listeners[type] || []).filter((item) => item !== cb);
  }

  close() {
    this.readyState = 3;
    this.closed = true;
  }

  _open() {
    this.readyState = 1;
    if (this.onopen) this.onopen({});
    (this.listeners.open || []).forEach((cb) => cb({}));
  }

  _message(data) {
    const event = { data: JSON.stringify(data) };
    if (this.onmessage) this.onmessage(event);
    (this.listeners.message || []).forEach((cb) => cb(event));
  }
}

// ---------------------------------------------------------------------------
// fixture
// ---------------------------------------------------------------------------
function makeV3Run() {
  return {
    id: 101,
    status: 'completed',
    block_count: 3,
    entity_count: 1,
    fact_count: 2,
    card_count: 1,
    updated_at: '2026-01-01T00:00:00',
    meta: { ai_invoked: false },
  };
}

function makeV1Run() {
  return {
    id: 201,
    status: 'completed',
    card_count: 0,
    pipeline_version: 'v1',
    updated_at: '2026-01-02T00:00:00',
  };
}

function makeEntity() {
  return {
    entity_uid: 'e1',
    canonical_name: '林岚',
    entity_type: 'character',
    status: 'candidate',
  };
}

function setupApiRouting() {
  api.get.mockImplementation((url) => {
    if (url === '/settings/workspace') {
      return Promise.resolve({ data: { analysis_pipeline_mode: 'v3' } });
    }
    if (url.endsWith('/analysis-v3/runs')) {
      return Promise.resolve({ data: { items: [makeV3Run()] } });
    }
    if (/\/analysis-v3\/runs\/\d+\/(blocks|mentions)$/.test(url)) {
      return Promise.resolve({ data: { items: [] } });
    }
    if (/\/analysis-v3\/runs\/\d+\/entities$/.test(url)) {
      return Promise.resolve({ data: { items: [makeEntity()] } });
    }
    if (/\/analysis-v3\/runs\/\d+\/(facts|cards|events)$/.test(url)) {
      return Promise.resolve({ data: { items: [] } });
    }
    if (/\/analysis-v3\/runs\/\d+\/probes\/(plans|results)$/.test(url)) {
      return Promise.resolve({ data: { items: [] } });
    }
    if (/\/analysis-v3\/runs\/\d+\/backtrack\/tasks$/.test(url)) {
      return Promise.resolve({ data: { items: [] } });
    }
    if (/\/analysis-v3\/runs\/\d+\/review$/.test(url)) {
      return Promise.resolve({
        data: {
          item: {
            entity_status_counts: { candidate: 1, reviewed: 0, merged: 0 },
            pending_backtrack_count: 0,
            manual_review_probe_count: 0,
          },
        },
      });
    }
    if (/\/workspace\/analysis\/runs\/\d+\/cards$/.test(url)) {
      return Promise.resolve({ data: { items: [] } });
    }
    if (url.endsWith('/analysis/runs')) {
      return Promise.resolve({ data: { items: [makeV1Run()] } });
    }
    return Promise.resolve({ data: { items: [] } });
  });
  api.post.mockResolvedValue({ data: {} });
  api.put.mockImplementation((url) => {
    if (url === '/settings/workspace') {
      return Promise.resolve({ data: { analysis_pipeline_mode: 'v3' } });
    }
    return Promise.resolve({ data: {} });
  });
  api.patch.mockResolvedValue({
    data: { writeback_result: { applied_id: 9, applied_table: 'characters', detail: 'characters #9' } },
  });
  api.delete.mockResolvedValue({ data: {} });
}

function getUrls(method) {
  return api[method].mock.calls.map((call) => call[0]);
}

async function createWrapper() {
  const pinia = createPinia();
  setActivePinia(pinia);
  const bookStore = useBookStore();
  bookStore.currentBook = { id: 1, title: '测试作品' };
  const authStore = useAuthStore();
  authStore.token = 'test-token';

  const wrapper = mount(AnalysisTab, {
    global: {
      plugins: [pinia, ElementPlus],
    },
  });
  await flushPromises();
  return wrapper;
}

describe('AnalysisTab', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    global.WebSocket = MockWebSocket;
    vi.clearAllMocks(); // 清掉上一条用例的调用记录（mock 为模块级单例）
    eventBusState.handlers = {};
    eventBusState.emitted = [];
    setupApiRouting();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('挂载成功并渲染主要分区（V3 运行记录 / 实体 / 草案卡 / 探针 / 回溯 / 语义块）', async () => {
    const wrapper = await createWrapper();
    expect(wrapper.find('.analysis-tab').exists()).toBe(true);
    expect(wrapper.find('.tab-title').text()).toBe('全书分析');
    expect(wrapper.text()).toContain('分析模式');
    // V3 运行记录区
    expect(wrapper.text()).toContain('V3 运行记录');
    expect(wrapper.text()).toContain('#101');
    // V3 工作流各分区（选中第一个 run 后 v3-workflow 渲染）
    expect(wrapper.find('.v3-workflow').exists()).toBe(true);
    expect(wrapper.text()).toContain('实体候选 (1 个)');
    expect(wrapper.text()).toContain('V3 草案卡候选 (0 张)');
    expect(wrapper.text()).toContain('回溯任务 (0 个)');
    expect(wrapper.text()).toContain('语义块诊断 (0 块)');
    // 概览分区
    expect(wrapper.text()).toContain('当前阶段');
    expect(wrapper.text()).toContain('章节块');
  });

  it('挂载时发起初始 api 调用清单（settings + V3 runs + 10 类诊断 + V1 runs + V1 cards）', async () => {
    await createWrapper();
    const urls = getUrls('get');
    expect(urls).toContain('/settings/workspace');
    expect(urls).toContain('/workspace/books/1/analysis-v3/runs');
    expect(urls).toContain('/workspace/analysis-v3/runs/101/blocks');
    expect(urls).toContain('/workspace/analysis-v3/runs/101/mentions');
    expect(urls).toContain('/workspace/analysis-v3/runs/101/entities');
    expect(urls).toContain('/workspace/analysis-v3/runs/101/facts');
    expect(urls).toContain('/workspace/analysis-v3/runs/101/cards');
    expect(urls).toContain('/workspace/analysis-v3/runs/101/events');
    expect(urls).toContain('/workspace/analysis-v3/runs/101/probes/plans');
    expect(urls).toContain('/workspace/analysis-v3/runs/101/probes/results');
    expect(urls).toContain('/workspace/analysis-v3/runs/101/backtrack/tasks');
    expect(urls).toContain('/workspace/analysis-v3/runs/101/review');
    expect(urls).toContain('/workspace/books/1/analysis/runs');
    expect(urls).toContain('/workspace/analysis/runs/201/cards');
    // settings 只在挂载时拉取一次
    expect(urls.filter((url) => url === '/settings/workspace').length).toBe(1);
  });

  it('未选择作品时：显示空提示、不拉运行列表（但设置仍会加载）', async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    mount(AnalysisTab, { global: { plugins: [pinia, ElementPlus] } });
    await flushPromises();

    const urls = getUrls('get');
    expect(urls).toContain('/settings/workspace');
    expect(urls.filter((url) => url.includes('/analysis-v3/runs')).length).toBe(0);
    expect(urls.filter((url) => url.includes('/analysis/runs')).length).toBe(0);
  });

  it('点击刷新按钮（V3 模式）→ 再次请求 V3 运行列表', async () => {
    const wrapper = await createWrapper();
    const before = getUrls('get').filter((url) => url.endsWith('/analysis-v3/runs')).length;
    expect(before).toBe(1);

    const refreshBtn = wrapper.findAll('button').find((btn) => btn.text().includes('刷新'));
    expect(refreshBtn).toBeTruthy();
    await refreshBtn.trigger('click');
    await flushPromises();

    const after = getUrls('get').filter((url) => url.endsWith('/analysis-v3/runs')).length;
    expect(after).toBe(2);
  });

  it('切换到 V1 模式：渲染 V1 分区，点击刷新 → 请求 V1 运行列表', async () => {
    const wrapper = await createWrapper();
    wrapper.vm.analysisMode = 'v1';
    await flushPromises();

    expect(wrapper.text()).toContain('V1 运行记录');
    expect(wrapper.text()).toContain('分析全文');
    expect(wrapper.text()).not.toContain('V3 运行记录');

    const before = getUrls('get').filter((url) => url.endsWith('/analysis/runs')).length;
    const refreshBtn = wrapper.findAll('button').find((btn) => btn.text().includes('刷新'));
    await refreshBtn.trigger('click');
    await flushPromises();

    const after = getUrls('get').filter((url) => url.endsWith('/analysis/runs')).length;
    expect(after).toBe(before + 1);
  });

  it('saveWorkspaceSettings → PUT /settings/workspace（携带当前设置）', async () => {
    const wrapper = await createWrapper();
    expect(getUrls('put').length).toBe(0);

    await wrapper.vm.saveWorkspaceSettings();
    await flushPromises();

    expect(api.put).toHaveBeenCalledTimes(1);
    expect(api.put).toHaveBeenCalledWith('/settings/workspace', {
      analysis_pipeline_mode: 'v3',
    });
  });

  it('markEntityReviewed：确认后 PATCH 实体状态并通过 eventBus 通知写回完成', async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm');
    const wrapper = await createWrapper();
    expect(getUrls('patch').length).toBe(0);

    await wrapper.vm.markEntityReviewed(makeEntity());
    await flushPromises();

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(api.patch).toHaveBeenCalledWith(
      '/workspace/analysis-v3/runs/101/entities/e1',
      { status: 'reviewed', actor: 'user' },
    );
    // 审核写回后重新拉诊断 + 运行列表
    expect(getUrls('get').filter((url) => url.endsWith('/analysis-v3/runs')).length).toBe(2);

    const events = eventBusState.emitted.map((item) => item.event);
    expect(events).toContain('lingshu:characters-updated');
    expect(events).toContain('lingshu:writeback-completed');
    const wb = eventBusState.emitted.find((item) => item.event === 'lingshu:writeback-completed');
    expect(wb.payload).toMatchObject({ bookId: 1, runId: 101, entityUid: 'e1', writebackTarget: 'character' });
  });

  it('markEntityReviewed：取消确认则不发 PATCH', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel');
    const wrapper = await createWrapper();

    await wrapper.vm.markEntityReviewed(makeEntity());
    await flushPromises();

    expect(api.patch).not.toHaveBeenCalled();
  });

  it('runActiveProbe：POST 主动探针并写入 localStorage 历史', async () => {
    api.post.mockResolvedValue({ data: { answer: '是主角', probe_mode: 'active' } });
    const wrapper = await createWrapper();
    wrapper.vm.activeProbeQuery = '主角是谁';
    localStorage.setItem.mockClear();

    await wrapper.vm.runActiveProbe();
    await flushPromises();

    expect(api.post).toHaveBeenCalledWith('/workspace/books/1/active-probe', { query: '主角是谁' });
    expect(localStorage.setItem).toHaveBeenCalledWith(
      'lingshu_active_probes_1',
      expect.stringContaining('是主角'),
    );
    // 成功后清空输入
    expect(wrapper.vm.activeProbeQuery).toBe('');
  });

  it('WebSocket：挂载即建连（/ws/analysis-v3）并在 open 后发送鉴权帧', async () => {
    await createWrapper();
    expect(MockWebSocket.instances.length).toBe(1);
    const ws = MockWebSocket.instances[0];
    expect(ws.url).toBe('ws://mock.test/ws/analysis-v3');

    ws._open();
    expect(ws.sent.length).toBe(1);
    expect(ws.sent[0]).toEqual({ type: 'auth', payload: { token: 'test-token' } });
  });

  it('WebSocket：收到 analysis_v3.writeback_completed → 转发 eventBus 并刷新诊断', async () => {
    await createWrapper();
    const ws = MockWebSocket.instances[0];
    ws._open();

    const runsBefore = getUrls('get').filter((url) => url.endsWith('/analysis-v3/runs')).length;
    ws._message({
      type: 'analysis_v3.writeback_completed',
      payload: { bookId: 1, run_id: 101, batch: true },
    });
    await flushPromises();

    const events = eventBusState.emitted.map((item) => item.event);
    expect(events).toContain('lingshu:characters-updated');
    expect(events).toContain('lingshu:world-updated');
    expect(events).toContain('lingshu:book-updated');
    expect(events).toContain('lingshu:writeback-completed');
    // batch 广播不带 writebackTarget
    const wb = eventBusState.emitted.find((item) => item.event === 'lingshu:writeback-completed');
    expect(wb.payload.writebackTarget).toBeUndefined();
    expect(wb.payload.source).toBe('ws');
    // 当前 run 选中时重新拉诊断 + 运行列表
    expect(getUrls('get').filter((url) => url.endsWith('/analysis-v3/runs')).length).toBe(runsBefore + 1);

    // 非本书记录被忽略
    eventBusState.handlers = {};
    eventBusState.emitted = [];
    ws._message({
      type: 'analysis_v3.writeback_completed',
      payload: { bookId: 999, run_id: 101, batch: true },
    });
    await flushPromises();
    expect(eventBusState.emitted.length).toBe(0);

    // 其他消息类型被忽略
    ws._message({ type: 'analysis_v3.progress', payload: { percent: 50 } });
    await flushPromises();
    expect(eventBusState.emitted.length).toBe(0);
  });

  it('卸载时断开 WebSocket 连接并注销 eventBus 监听', async () => {
    const wrapper = await createWrapper();
    const ws = MockWebSocket.instances[0];
    const handlerCount = (eventBusState.handlers['lingshu:book-analysis-start'] || []).length;
    expect(handlerCount).toBe(1);

    wrapper.unmount();

    expect(ws.closed).toBe(true);
    expect((eventBusState.handlers['lingshu:book-analysis-start'] || []).length).toBe(0);
  });
});
