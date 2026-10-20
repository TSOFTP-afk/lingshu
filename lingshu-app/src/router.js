import { createRouter, createWebHistory } from 'vue-router';
import AppLayout from './components/layout/AppLayout.vue';

const routes = [
  {
    path: '/',
    component: AppLayout,
    children: [
      {
        path: '',
        redirect: '/workspace',
      },
      {
        path: 'settings/:section?',
        name: 'settings',
        component: () => import('./components/settings/SettingsView.vue'),
      },
      {
        path: 'workspace',
        name: 'workspace-entry',
        component: () => import('./components/workspace/WorkspaceLayout.vue'),
      },
      {
        path: 'workspace/books/:bookId',
        name: 'workspace-book',
        component: () => import('./components/workspace/WorkspaceLayout.vue'),
      },
      {
        path: 'workspace/books/:bookId/volumes/:volumeId',
        name: 'workspace-volume',
        component: () => import('./components/workspace/WorkspaceLayout.vue'),
      },
      {
        path: 'workspace/books/:bookId/volumes/:volumeId/chapters/:chapterId',
        name: 'workspace-chapter',
        component: () => import('./components/workspace/WorkspaceLayout.vue'),
      },
      {
        path: 'workspace/books/:bookId/settings',
        name: 'workspace-book-settings',
        redirect: to => ({
          path: '/settings/general',
          query: { bookId: to.params.bookId },
        }),
      },
      {
        path: 'workspace/books/:bookId/chat',
        name: 'workspace-chat',
        component: () => import('./components/workspace/WorkspaceLayout.vue'),
      },
      {
        path: 'workspace/books/:bookId/reference',
        name: 'workspace-reference',
        component: () => import('./components/workspace/WorkspaceLayout.vue'),
      },
      {
        path: 'workspace/books/:bookId/star-graph',
        name: 'workspace-star-graph',
        component: () => import('./components/workspace/WorkspaceLayout.vue'),
      },
      {
        path: 'workspace/import',
        name: 'workspace-import',
        component: () => import('./components/workspace/WorkspaceLayout.vue'),
      },
      {
        path: 'workspace/settings',
        name: 'workspace-settings',
        redirect: '/settings',
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/workspace',
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 };
  },
});

router.afterEach((to) => {
  if (to.path.startsWith('/workspace') && to.path !== '/workspace/settings') {
    localStorage.setItem('lingshu_last_workspace_path', to.fullPath);
  }
});
