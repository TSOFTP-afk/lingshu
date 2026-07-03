import { mount } from '@vue/test-utils';
import { describe, it, expect, vi } from 'vitest';
import App from '../src/App.vue';

// Mock axios to prevent real HTTP requests
vi.mock('axios', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    patch: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: {} })),
  },
}));

// Mock vue-echarts to avoid ECharts initialization in jsdom
vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    render() { return null; },
  },
}));

describe('App.vue', () => {
  it('renders without errors', () => {
    const wrapper = mount(App, {
      global: {
        stubs: {
          ElAlert: true,
          ElForm: true,
          ElFormItem: true,
          ElInput: true,
          ElButton: true,
          ElContainer: true,
          ElAside: true,
          ElHeader: true,
          ElMain: true,
          ElMenu: true,
          ElMenuItem: true,
          ElIcon: true,
          ElTag: true,
          ElTable: true,
          ElTableColumn: true,
          ElPagination: true,
          ElDrawer: true,
          ElSelect: true,
          ElOption: true,
          ElSwitch: true,
          ElInputNumber: true,
          ElRadioButton: true,
          ElRadioGroup: true,
          VChart: true,
        },
      },
    });
    expect(wrapper.exists()).toBe(true);
  });

  it('shows login panel when not authenticated', () => {
    const wrapper = mount(App, {
      global: {
        stubs: {
          ElAlert: true,
          ElForm: true,
          ElFormItem: true,
          ElInput: true,
          ElButton: true,
          ElContainer: true,
          ElAside: true,
          ElHeader: true,
          ElMain: true,
          ElMenu: true,
          ElMenuItem: true,
          ElIcon: true,
          ElTag: true,
          ElTable: true,
          ElTableColumn: true,
          ElPagination: true,
          ElDrawer: true,
          ElSelect: true,
          ElOption: true,
          ElSwitch: true,
          ElInputNumber: true,
          ElRadioButton: true,
          ElRadioGroup: true,
          VChart: true,
        },
      },
    });
    // Login panel should be visible (class login-shell)
    const loginShell = wrapper.find('.login-shell');
    expect(loginShell.exists()).toBe(true);

    // Title "灵镜后台管理" should be present
    expect(wrapper.text()).toContain('灵镜后台管理');
  });

  it('contains login form elements', () => {
    const wrapper = mount(App, {
      global: {
        stubs: {
          ElAlert: true,
          ElForm: { template: '<form class="login-form"><slot /></form>' },
          ElFormItem: { template: '<div class="el-form-item"><slot /></div>' },
          ElInput: true,
          ElButton: { template: '<button><slot /></button>' },
          ElContainer: true,
          ElAside: true,
          ElHeader: true,
          ElMain: true,
          ElMenu: true,
          ElMenuItem: true,
          ElIcon: true,
          ElTag: true,
          ElTable: true,
          ElTableColumn: true,
          ElPagination: true,
          ElDrawer: true,
          ElSelect: true,
          ElOption: true,
          ElSwitch: true,
          ElInputNumber: true,
          ElRadioButton: true,
          ElRadioGroup: true,
          VChart: true,
        },
      },
    });
    // Login form should exist
    const loginForm = wrapper.find('.login-form');
    expect(loginForm.exists()).toBe(true);
  });
});
