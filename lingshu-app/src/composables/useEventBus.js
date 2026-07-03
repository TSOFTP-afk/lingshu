const listeners = new Map()

export function useEventBus() {
  function on(event, callback) {
    if (!listeners.has(event)) {
      listeners.set(event, new Set())
    }
    listeners.get(event).add(callback)
  }

  function off(event, callback) {
    if (listeners.has(event)) {
      listeners.get(event).delete(callback)
    }
  }

  function emit(event, payload) {
    if (listeners.has(event)) {
      listeners.get(event).forEach(cb => cb(payload))
    }
  }

  return { on, off, emit }
}
