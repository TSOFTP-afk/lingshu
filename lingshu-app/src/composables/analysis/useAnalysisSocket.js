// AnalysisTab 域拆分：WebSocket 连接 / 鉴权 / 消息监听 / eventBus 转发 / runV3AnalysisOverWs
// ctx 为主组件构造的共享上下文：跨域状态与函数一律通过 ctx 延迟读取（单一数据源，禁止复制）。
// 纯搬移自 src/components/drawer/AnalysisTab.vue，业务逻辑未改动。
import { buildWsUrl, sendWsAuth } from '../../utils/api';

const WS_PATH_ANALYSIS_V3 = '/ws/analysis-v3';
let _wsMessageHandler = null;

export function useAnalysisSocket(ctx) {
  const { wsStore } = ctx;

  function runV3AnalysisOverWs() {
    return new Promise((resolve, reject) => {
      const taskId = `analysis-v3-${Date.now()}`;
      const ws = new WebSocket(buildWsUrl(WS_PATH_ANALYSIS_V3));
      const { bookId, useAiAnalysis, analysisV3Progress } = ctx;
      let settled = false;
      let analyzeSent = false;
      let lastProgressTime = Date.now();
      const timer = setTimeout(() => {
        finish(new Error('分析超时，请稍后重试'));
      }, 30 * 60 * 1000);
      const stallChecker = setInterval(() => {
        if (Date.now() - lastProgressTime > 60000 && !settled) {
          finish(new Error('分析长时间无进度更新，可能是 AI 调用超时或服务异常，请检查 AI 配置或稍后重试'));
        }
      }, 10000);

      function cleanup() {
        clearTimeout(timer);
        clearInterval(stallChecker);
        try { ws.close(); } catch { /* ignore */ }
      }

      function finish(error, data = null) {
        if (settled) return;
        settled = true;
        cleanup();
        if (error) reject(error);
        else resolve(data);
      }

      ws.onopen = () => {
        const token = sendWsAuth(ws);
        if (!token) {
          finish(new Error('请先登录后再分析'));
        }
      };

      ws.onmessage = (event) => {
        let message;
        try { message = JSON.parse(event.data); } catch { return; }

        if (message.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong' }));
          return;
        }

        if (message.type === 'auth_ok' && !analyzeSent) {
          analyzeSent = true;
          lastProgressTime = Date.now();
          ws.send(JSON.stringify({
            type: 'analyze_v3',
            task_id: taskId,
            payload: { book_id: bookId.value, use_ai: useAiAnalysis.value },
          }));
          return;
        }

        if (message.task_id && message.task_id !== taskId) return;
        const payload = message.payload || {};

        if (message.type === 'analysis_v3.progress') {
          lastProgressTime = Date.now();
          analysisV3Progress.value = {
            percent: Number(payload.percent || 0),
            message: payload.message || '',
          };
        } else if (message.type === 'analysis_v3.result') {
          if (payload.status === 'cancelled') {
            finish(new Error('分析已取消'));
          } else {
            finish(null, payload);
          }
        } else if (message.type === 'analysis_v3.error') {
          finish(new Error(payload.message || '分析失败'));
        }
      };

      ws.onerror = () => finish(new Error('分析连接失败'));
      ws.onclose = (event) => {
        if (!settled) {
          finish(new Error(`分析连接已断开：${event.code || ''}`));
        }
      };
    });
  }

  function _setupWsListener() {
    try {
      const ws = wsStore.connect(WS_PATH_ANALYSIS_V3);
      _wsMessageHandler = (event) => {
        if (!event || !event.data) return;
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (message.type !== 'analysis_v3.writeback_completed') return;
        const payload = message.payload || {};
        // 仅处理当前书籍的写回事件
        if (payload.bookId && ctx.bookId.value && Number(payload.bookId) !== Number(ctx.bookId.value)) return;
        // 通过 eventBus 转发，让 CharactersTab/WorldTab 等组件刷新
        if (payload.batch) {
          ctx.emit('lingshu:characters-updated', { bookId: payload.bookId, source: 'ws_writeback' });
          ctx.emit('lingshu:world-updated', { bookId: payload.bookId, source: 'ws_writeback' });
          ctx.emit('lingshu:book-updated', { bookId: payload.bookId, source: 'ws_writeback' });
        }
        ctx.emit('lingshu:writeback-completed', {
          bookId: payload.bookId,
          runId: payload.run_id,
          cardUid: payload.card_uid,
          appliedTable: payload.applied_table,
          appliedId: payload.applied_id,
          // 批量写回不带 writebackTarget，依赖 store 的"不带字段则刷新"逻辑
          writebackTarget: payload.batch ? undefined : (payload.applied_table === 'characters' ? 'character'
            : payload.applied_table === 'world_entries' ? 'world_entry'
            : payload.applied_table === 'books' ? 'book' : undefined),
          source: 'ws',
        });
        // 同步刷新当前 tab 的 V3 诊断和运行列表
        if (payload.run_id && ctx.selectedV3RunId.value) {
          ctx.loadV3RunDiagnostics(ctx.selectedV3RunId.value);
          ctx.loadV3Runs(ctx.selectedV3RunId.value);
        }
      };
      ws.addEventListener('message', _wsMessageHandler);
    } catch (e) {
      // WebSocket 连接失败不影响核心功能
      console.warn('[AnalysisTab] WebSocket 连接失败:', e);
    }
  }

  function _teardownWsListener() {
    if (_wsMessageHandler) {
      try {
        const ws = wsStore.connections[WS_PATH_ANALYSIS_V3];
        if (ws) ws.removeEventListener('message', _wsMessageHandler);
      } catch { /* ignore */ }
      _wsMessageHandler = null;
    }
    wsStore.disconnect(WS_PATH_ANALYSIS_V3);
  }

  return { runV3AnalysisOverWs, _setupWsListener, _teardownWsListener };
}
