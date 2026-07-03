import { describe, it, expect } from 'vitest';

describe('测试框架配置', () => {
  it('Vitest 应正确运行', () => {
    expect(1 + 1).toBe(2);
  });

  it('jsdom 环境应可用', () => {
    expect(typeof window).toBe('object');
  });

  it('localStorage 应可用', () => {
    localStorage.setItem('test', 'value');
    expect(localStorage.getItem('test')).toBe('value');
  });
});
