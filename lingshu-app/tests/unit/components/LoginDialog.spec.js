import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ElementPlus from 'element-plus';
import LoginDialog from '../../../src/components/dialogs/LoginDialog.vue';

// el-dialog with append-to-body teleports content outside the wrapper,
// so we stub it to render content inline for testing.
const globalStubs = {
  'el-dialog': {
    template: `
      <div class="el-dialog-stub login-dialog">
        <slot name="header" />
        <slot />
        <slot name="footer" />
      </div>
    `,
    props: ['modelValue'],
  },
};

function createWrapper(props = {}) {
  return mount(LoginDialog, {
    props: {
      modelValue: true,
      ...props,
    },
    global: {
      plugins: [createPinia(), ElementPlus],
      stubs: globalStubs,
    },
  });
}

describe('LoginDialog', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('renders without errors', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.login-dialog').exists()).toBe(true);
  });

  it('displays login title', () => {
    const wrapper = createWrapper();
    expect(wrapper.text()).toContain('登录灵枢');
  });

  it('shows login and register tab labels', () => {
    const wrapper = createWrapper();
    expect(wrapper.text()).toContain('登录');
    expect(wrapper.text()).toContain('注册');
  });

  it('displays form fields for username and password', () => {
    const wrapper = createWrapper();
    const formItems = wrapper.findAllComponents({ name: 'ElFormItem' });
    expect(formItems.length).toBeGreaterThanOrEqual(2);
  });

  it('shows confirm password field only in register mode', async () => {
    const wrapper = createWrapper();
    // In login mode, confirm password should not be visible
    expect(wrapper.text()).not.toContain('确认密码');

    // Switch to register tab
    const vm = wrapper.vm;
    vm.activeTab = 'register';
    await wrapper.vm.$nextTick();
    expect(wrapper.text()).toContain('确认密码');
  });

  it('displays terms checkbox', () => {
    const wrapper = createWrapper();
    expect(wrapper.findComponent({ name: 'ElCheckbox' }).exists()).toBe(true);
  });

  it('shows error alert when auth has error', async () => {
    const wrapper = createWrapper();
    const authStore = wrapper.vm.auth;
    authStore.error = '用户名或密码错误';
    await wrapper.vm.$nextTick();
    expect(wrapper.findComponent({ name: 'ElAlert' }).exists()).toBe(true);
  });

  it('emits update:modelValue when cancel button is clicked', async () => {
    const wrapper = createWrapper();
    const buttons = wrapper.findAllComponents({ name: 'ElButton' });
    // First button is cancel
    const cancelButton = buttons[0];
    await cancelButton.trigger('click');
    expect(wrapper.emitted('update:modelValue')).toBeTruthy();
    expect(wrapper.emitted('update:modelValue')[0][0]).toBe(false);
  });

  it('shows loading state on submit button when auth is loading', async () => {
    const wrapper = createWrapper();
    const authStore = wrapper.vm.auth;
    authStore.loading = true;
    await wrapper.vm.$nextTick();
    const submitButton = wrapper.findAllComponents({ name: 'ElButton' }).at(-1);
    expect(submitButton.props('loading')).toBe(true);
  });

  it('displays avatar initial from username', async () => {
    const wrapper = createWrapper();
    const vm = wrapper.vm;
    vm.form.username = '测试';
    await wrapper.vm.$nextTick();
    expect(wrapper.find('.login-avatar').text()).toBe('测');
  });

  it('defaults avatar initial to 灵 when no username', () => {
    const wrapper = createWrapper();
    expect(wrapper.find('.login-avatar').text()).toBe('灵');
  });

  it('computes avatarInitial correctly', () => {
    const wrapper = createWrapper();
    expect(wrapper.vm.avatarInitial).toBe('灵');
    wrapper.vm.form.username = 'Hello';
    expect(wrapper.vm.avatarInitial).toBe('H');
  });

  it('submit does not call auth.login with empty username', async () => {
    const wrapper = createWrapper();
    const authStore = wrapper.vm.auth;
    const loginSpy = vi.spyOn(authStore, 'login');
    wrapper.vm.form.username = '';
    wrapper.vm.form.password = 'test1234';
    await wrapper.vm.submit();
    expect(loginSpy).not.toHaveBeenCalled();
  });

  it('submit does not call auth.login with empty password', async () => {
    const wrapper = createWrapper();
    const authStore = wrapper.vm.auth;
    const loginSpy = vi.spyOn(authStore, 'login');
    wrapper.vm.form.username = 'testuser';
    wrapper.vm.form.password = '';
    await wrapper.vm.submit();
    expect(loginSpy).not.toHaveBeenCalled();
  });

  it('submit calls auth.login with valid credentials', async () => {
    const wrapper = createWrapper();
    const authStore = wrapper.vm.auth;
    const loginSpy = vi.spyOn(authStore, 'login').mockResolvedValue({});
    wrapper.vm.form.username = 'testuser';
    wrapper.vm.form.password = 'test1234';
    await wrapper.vm.submit();
    expect(loginSpy).toHaveBeenCalledWith('testuser', 'test1234');
  });

  it('submit calls auth.register in register mode', async () => {
    const wrapper = createWrapper();
    const authStore = wrapper.vm.auth;
    const registerSpy = vi.spyOn(authStore, 'register').mockResolvedValue({});
    wrapper.vm.activeTab = 'register';
    wrapper.vm.form.username = 'newuser';
    wrapper.vm.form.password = 'Test1234';
    wrapper.vm.form.confirmPassword = 'Test1234';
    await wrapper.vm.submit();
    expect(registerSpy).toHaveBeenCalledWith('newuser', 'Test1234', 1);
  });
});
