/**
 * WebSocket Store — 连接管理（含自动重连）
 */
import { defineStore } from 'pinia';
import { ref } from 'vue';
import { buildWsUrl, sendWsAuth } from '../utils/api';

const RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_ATTEMPTS = 5;

export const useWsStore = defineStore('ws', () => {
  const connections = ref({});
  const status = ref({});
  const reconnectAttempts = ref({});

  function connect(url) {
    if (connections.value[url]) return connections.value[url];

    const ws = new WebSocket(buildWsUrl(url));
    let intentionalClose = false;

    ws.onopen = () => {
      status.value[url] = 'connected';
      reconnectAttempts.value[url] = 0;
      // 重连后重新发送认证消息
      const token = sendWsAuth(ws);
      if (!token) {
        intentionalClose = true;
        status.value[url] = 'unauthenticated';
        ws.close();
      }
    };
    ws.onclose = (event) => {
      status.value[url] = 'disconnected';
      delete connections.value[url];
      // 主动断开时不重连
      if (intentionalClose) return;
      // 认证失败/封禁类关闭码不自动重连，避免空 token 循环触发后端风控。
      if ([4001, 4003, 4004].includes(event?.code)) {
        status.value[url] = 'unauthenticated';
        return;
      }
      // 自动重连（指数退避）
      const attempts = reconnectAttempts.value[url] || 0;
      if (attempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts.value[url] = attempts + 1;
        const delay = RECONNECT_DELAY_MS * Math.pow(2, attempts);
        setTimeout(() => {
          if (!connections.value[url]) {
            connect(url);
          }
        }, delay);
      }
    };
    ws.onerror = () => { status.value[url] = 'error'; };

    connections.value[url] = ws;
    status.value[url] = 'connecting';
    // 保存 intentionalClose 标志以便 disconnect 使用
    ws._setIntentionalClose = () => { intentionalClose = true; };
    return ws;
  }

  function disconnect(url) {
    const ws = connections.value[url];
    if (ws) {
      if (ws._setIntentionalClose) ws._setIntentionalClose();
      ws.close();
      delete connections.value[url];
      delete reconnectAttempts.value[url];
    }
  }

  function send(url, message) {
    const ws = connections.value[url];
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message));
    }
  }

  function disconnectAll() {
    Object.keys(connections.value).forEach(disconnect);
  }

  return { connections, status, connect, disconnect, send, disconnectAll };
});
