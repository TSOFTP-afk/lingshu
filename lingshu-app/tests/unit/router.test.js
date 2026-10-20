import { describe, it, expect, vi, beforeEach } from 'vitest';
import { router } from '../../src/router';

describe('Router Configuration', () => {
  beforeEach(async () => {
    // Reset router to a known state before each test
    await router.push('/workspace');
    await router.isReady();
    localStorage.clear();
    vi.clearAllMocks();
  });

  // 1. Route definitions exist for all paths
  describe('Route definitions', () => {
    it('should define a route for /settings/:section?', () => {
      const routes = router.getRoutes();
      const settingsRoute = routes.find((r) => r.name === 'settings');
      expect(settingsRoute).toBeDefined();
      expect(settingsRoute.path).toBe('/settings/:section?');
    });

    it('should define workspace entry route', () => {
      const routes = router.getRoutes();
      const route = routes.find((r) => r.name === 'workspace-entry');
      expect(route).toBeDefined();
    });

    it('should define workspace book route', () => {
      const routes = router.getRoutes();
      const route = routes.find((r) => r.name === 'workspace-book');
      expect(route).toBeDefined();
    });

    it('should define workspace volume route', () => {
      const routes = router.getRoutes();
      const route = routes.find((r) => r.name === 'workspace-volume');
      expect(route).toBeDefined();
    });

    it('should define workspace chapter route', () => {
      const routes = router.getRoutes();
      const route = routes.find((r) => r.name === 'workspace-chapter');
      expect(route).toBeDefined();
    });

    it('should define workspace book settings redirect route', () => {
      const routes = router.getRoutes();
      const route = routes.find((r) => r.name === 'workspace-book-settings');
      expect(route).toBeDefined();
    });

    it('should define workspace chat route', () => {
      const routes = router.getRoutes();
      const route = routes.find((r) => r.name === 'workspace-chat');
      expect(route).toBeDefined();
    });

    it('should define workspace reference route', () => {
      const routes = router.getRoutes();
      const route = routes.find((r) => r.name === 'workspace-reference');
      expect(route).toBeDefined();
    });

    it('should define workspace star-graph route', () => {
      const routes = router.getRoutes();
      const route = routes.find((r) => r.name === 'workspace-star-graph');
      expect(route).toBeDefined();
    });

    it('should define workspace import route', () => {
      const routes = router.getRoutes();
      const route = routes.find((r) => r.name === 'workspace-import');
      expect(route).toBeDefined();
    });

    it('should define workspace settings redirect route', () => {
      const routes = router.getRoutes();
      const route = routes.find((r) => r.name === 'workspace-settings');
      expect(route).toBeDefined();
    });

    it('should define a catch-all 404 route', () => {
      const routes = router.getRoutes();
      const catchAll = routes.find((r) => r.path === '/:pathMatch(.*)*');
      expect(catchAll).toBeDefined();
    });
  });

  // 2. Navigation to / redirects to /workspace
  it('redirects / to /workspace', async () => {
    await router.push('/');
    expect(router.currentRoute.value.path).toBe('/workspace');
  });

  // 3. Navigation to /workspace resolves correctly
  it('resolves /workspace correctly', async () => {
    await router.push('/workspace');
    const route = router.currentRoute.value;
    expect(route.path).toBe('/workspace');
    expect(route.name).toBe('workspace-entry');
  });

  // 3.1 /workspace/books/:bookId 路由参数解析
  it('resolves /workspace/books/:bookId and parses bookId param', async () => {
    await router.push('/workspace/books/42');
    const route = router.currentRoute.value;
    expect(route.path).toBe('/workspace/books/42');
    expect(route.name).toBe('workspace-book');
    expect(route.params.bookId).toBe('42');
  });

  // 4. Navigation to /settings resolves correctly
  it('resolves /settings correctly', async () => {
    await router.push('/settings');
    const route = router.currentRoute.value;
    expect(route.path).toBe('/settings');
    expect(route.name).toBe('settings');
  });

  it('resolves /settings/general correctly', async () => {
    await router.push('/settings/general');
    const route = router.currentRoute.value;
    expect(route.path).toBe('/settings/general');
    expect(route.name).toBe('settings');
    expect(route.params.section).toBe('general');
  });

  // 5. 404 paths redirect to /workspace
  it('redirects unknown paths to /workspace', async () => {
    await router.push('/nonexistent-path-xyz');
    expect(router.currentRoute.value.path).toBe('/workspace');
  });

  it('redirects removed community route to /workspace', async () => {
    await router.push('/community');
    expect(router.currentRoute.value.path).toBe('/workspace');
  });

  it('redirects deeply nested unknown paths to /workspace', async () => {
    await router.push('/some/deeply/nested/unknown/path');
    expect(router.currentRoute.value.path).toBe('/workspace');
  });

  // 6. /workspace/books/:bookId/settings redirects to /settings/general
  it('redirects /workspace/books/:bookId/settings to /settings/general with bookId query', async () => {
    await router.push('/workspace/books/123/settings');
    const route = router.currentRoute.value;
    expect(route.path).toBe('/settings/general');
    expect(route.query.bookId).toBe('123');
  });

  // 7. /workspace/settings redirects to /settings
  it('redirects /workspace/settings to /settings', async () => {
    await router.push('/workspace/settings');
    expect(router.currentRoute.value.path).toBe('/settings');
  });

  // 8. afterEach hook saves workspace path to localStorage
  describe('afterEach hook - localStorage', () => {
    it('saves workspace path to localStorage on workspace navigation', async () => {
      await router.push('/workspace');
      expect(localStorage.setItem).toHaveBeenCalledWith(
        'lingshu_last_workspace_path',
        '/workspace'
      );
    });

    it('saves workspace book path to localStorage', async () => {
      await router.push('/workspace/books/42');
      expect(localStorage.setItem).toHaveBeenCalledWith(
        'lingshu_last_workspace_path',
        '/workspace/books/42'
      );
    });

    it('saves workspace chapter path to localStorage', async () => {
      await router.push('/workspace/books/1/volumes/2/chapters/3');
      expect(localStorage.setItem).toHaveBeenCalledWith(
        'lingshu_last_workspace_path',
        '/workspace/books/1/volumes/2/chapters/3'
      );
    });

    it('does not save to localStorage for non-workspace paths', async () => {
      localStorage.clear();
      vi.clearAllMocks();
      await router.push('/settings/general');
      expect(localStorage.setItem).not.toHaveBeenCalledWith(
        'lingshu_last_workspace_path',
        expect.anything()
      );
    });

    it('does not save /workspace/settings to localStorage', async () => {
      localStorage.clear();
      vi.clearAllMocks();
      // /workspace/settings redirects to /settings, so the final path is /settings
      // which doesn't start with /workspace, so it won't be saved
      await router.push('/workspace/settings');
      expect(localStorage.setItem).not.toHaveBeenCalledWith(
        'lingshu_last_workspace_path',
        expect.anything()
      );
    });

    it('saves full path including query string', async () => {
      await router.push('/workspace/books/99/chat?tab=open');
      expect(localStorage.setItem).toHaveBeenCalledWith(
        'lingshu_last_workspace_path',
        '/workspace/books/99/chat?tab=open'
      );
    });
  });
});
