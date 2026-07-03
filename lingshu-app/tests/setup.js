import { vi } from 'vitest';

// Mock Electron bridge
global.window.lingshu = undefined;

// Mock localStorage
const localStorageMock = (() => {
  let store = {};
  return {
    getItem: vi.fn((key) => store[key] ?? null),
    setItem: vi.fn((key, value) => { store[key] = String(value); }),
    removeItem: vi.fn((key) => { delete store[key]; }),
    clear: vi.fn(() => { store = {}; }),
    get length() { return Object.keys(store).length; },
    key: vi.fn((i) => Object.keys(store)[i] ?? null),
  };
})();
Object.defineProperty(global, 'localStorage', { value: localStorageMock });

// Mock document.dispatchEvent
if (typeof document !== 'undefined') {
  document.dispatchEvent = vi.fn();
}

// Suppress console.warn in tests
const originalWarn = console.warn;
console.warn = (...args) => {
  if (typeof args[0] === 'string' && args[0].includes('[Vue warn]')) return;
  originalWarn(...args);
};
