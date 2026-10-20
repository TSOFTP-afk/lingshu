import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import { createRouter, createMemoryHistory } from 'vue-router';
import SettingsView from '../../../src/components/settings/SettingsView.vue';

// Stub child components
const childStubs = {
  GeneralSettingsSection: { template: '<div class="stub-general-section">General</div>' },
  AiSettingsSection: { template: '<div class="stub-ai-section">AI</div>' },
  ReferenceBooksView: { template: '<div class="stub-reference-view" />' },
};

function createRouterInstance(initialRoute = '/settings') {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/settings', name: 'settings', component: { template: '<div />' } },
      { path: '/settings/:section', name: 'settings-section', component: { template: '<div />' } },
      { path: '/workspace', name: 'workspace', component: { template: '<div />' } },
    ],
  });
}

async function createWrapper(initialRoute = '/settings') {
  const pinia = createPinia();
  setActivePinia(pinia);
  const router = createRouterInstance(initialRoute);
  router.push(initialRoute);
  await router.isReady();

  const wrapper = mount(SettingsView, {
    global: {
      plugins: [pinia, ElementPlus, router],
      stubs: childStubs,
    },
  });

  return { wrapper, router };
}

describe('SettingsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('renders without errors', async () => {
    const { wrapper } = await createWrapper();
    expect(wrapper.find('.settings-view').exists()).toBe(true);
  });

  it('renders settings sidebar', async () => {
    const { wrapper } = await createWrapper();
    expect(wrapper.find('.settings-sidebar').exists()).toBe(true);
  });

  it('renders settings main area', async () => {
    const { wrapper } = await createWrapper();
    expect(wrapper.find('.settings-main').exists()).toBe(true);
  });

  it('displays back to workspace button', async () => {
    const { wrapper } = await createWrapper();
    expect(wrapper.find('.back-button').exists()).toBe(true);
    expect(wrapper.text()).toContain('返回工作台');
  });

  it('renders navigation items', async () => {
    const { wrapper } = await createWrapper();
    const navItems = wrapper.findAll('.nav-item');
    expect(navItems.length).toBeGreaterThanOrEqual(8);
  });

  it('renders profile block with avatar', async () => {
    const { wrapper } = await createWrapper();
    expect(wrapper.find('.profile-block').exists()).toBe(true);
    expect(wrapper.find('.profile-avatar').exists()).toBe(true);
  });

  it('renders search input', async () => {
    const { wrapper } = await createWrapper();
    expect(wrapper.find('.settings-search').exists()).toBe(true);
  });

  it('defaults to general section when no section param', async () => {
    const { wrapper } = await createWrapper('/settings');
    expect(wrapper.vm.activeSection).toBe('general');
  });

  it('navigates to correct section from route params', async () => {
    const { wrapper } = await createWrapper('/settings/ai');
    expect(wrapper.vm.activeSection).toBe('ai');
  });

  it('shows general section by default', async () => {
    const { wrapper } = await createWrapper();
    expect(wrapper.find('.stub-general-section').exists()).toBe(true);
  });

  it('has no account section (本地模式无账号)', async () => {
    const { wrapper } = await createWrapper();
    const navItems = wrapper.findAll('.nav-item');
    const labels = navItems.map((item) => item.text());
    expect(labels).not.toContain('账号');
    expect(wrapper.text()).not.toContain('退出登录');
  });

  it('shows AI section when activeSection is ai', async () => {
    const { wrapper } = await createWrapper('/settings/ai');
    expect(wrapper.find('.stub-ai-section').exists()).toBe(true);
  });

  it('filters navigation items by search query', async () => {
    const { wrapper } = await createWrapper();
    wrapper.vm.searchQuery = 'AI';
    await wrapper.vm.$nextTick();
    const visibleGroups = wrapper.vm.visibleGroups;
    expect(visibleGroups.length).toBeGreaterThan(0);
    // All visible items should contain 'AI' related keywords
    const allLabels = visibleGroups.flatMap(g => g.items.map(i => i.label));
    expect(allLabels.some(l => l.includes('AI') || l.includes('配置'))).toBe(true);
  });

  it('shows no results message when search has no matches', async () => {
    const { wrapper } = await createWrapper();
    wrapper.vm.searchQuery = 'zzzznonexistent';
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.nav-empty').exists()).toBe(true);
  });
});
