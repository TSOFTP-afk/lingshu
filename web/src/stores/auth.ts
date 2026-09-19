import { defineStore } from 'pinia';
import { ref } from 'vue';
import axios from 'axios';

interface AuthUser {
  id: number;
  username: string;
  is_author: number;
  bind_reader_id: number | null;
  bind_reader_name: string | null;
}

export const useAuth = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null);
  const token = ref(sessionStorage.getItem('auth_token') || '');
  const loading = ref(false);
  const showLoginModal = ref(false);

  function setAuth(newToken: string, newUser: AuthUser) {
    token.value = newToken;
    user.value = newUser;
    sessionStorage.setItem('auth_token', newToken);
    showLoginModal.value = false;
  }

  function logout() {
    token.value = '';
    user.value = null;
    sessionStorage.removeItem('auth_token');
  }

  async function fetchMe() {
    if (!token.value) return;
    try {
      const res = await axios.get('/api/auth/me', {
        headers: { Authorization: `Bearer ${token.value}` },
      });
      user.value = res.data;
    } catch {
      logout();
    }
  }

  async function login(username: string, password: string) {
    loading.value = true;
    try {
      const res = await axios.post('/api/auth/login', {
        username,
        password,
      });
      setAuth(res.data.access_token, res.data.user);
      return true;
    } catch (e: any) {
      if (e?.response?.status === 429) throw new Error('请求过于频繁，请稍后再试');
      throw new Error(e?.response?.data?.detail || '登录失败');
    } finally {
      loading.value = false;
    }
  }

  async function register(username: string, password: string, isAuthor: boolean = true) {
    loading.value = true;
    try {
      const res = await axios.post('/api/auth/register', {
        username,
        password,
        is_author: isAuthor ? 1 : 0,
      });
      setAuth(res.data.access_token, res.data.user);
      return true;
    } catch (e: any) {
      if (e?.response?.status === 429) throw new Error('请求过于频繁，请稍后再试');
      if (e?.response?.status === 409) throw new Error('用户名已存在');
      throw new Error(e?.response?.data?.detail || '注册失败');
    } finally {
      loading.value = false;
    }
  }

  function openLogin() {
    showLoginModal.value = true;
  }

  return { user, token, loading, showLoginModal, login, register, logout, fetchMe, openLogin };
});
