import { createRouter, createWebHistory } from 'vue-router';

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('./views/HomeView.vue') },
    { path: '/bookstore', name: 'bookstore', component: () => import('./views/BookstoreView.vue') },
    { path: '/shelf', name: 'bookshelf', component: () => import('./views/BookshelfView.vue'), meta: { requiresAuth: true } },
    { path: '/profile', name: 'profile', component: () => import('./views/ProfileView.vue'), meta: { requiresAuth: true } },
    { path: '/profile/books/:bookId', name: 'profile-book-detail', component: () => import('./views/ProfileView.vue'), meta: { requiresAuth: true }, props: true },
    { path: '/profile/books/:bookId/chapters', name: 'author-chapters', component: () => import('./views/AuthorChapterManageView.vue'), meta: { requiresAuth: true }, props: true },
    { path: '/profile/books/:bookId/chapters/:chapterId/edit', name: 'author-chapter-edit', component: () => import('./views/AuthorChapterEditorView.vue'), meta: { requiresAuth: true }, props: true },
    { path: '/books/:bookId', name: 'book-detail', component: () => import('./views/BookDetailView.vue'), props: true },
    { path: '/books/:bookId/chapters/:chapterId', name: 'reader', component: () => import('./views/ReaderView.vue'), props: true },
  ],
  scrollBehavior() {
    return { top: 0 };
  },
});

router.beforeEach((to) => {
  if (to.meta.requiresAuth) {
    const token = sessionStorage.getItem('auth_token') || sessionStorage.getItem('lingshu_token');
    if (!token) {
      return { name: 'home', query: { redirect: to.fullPath } };
    }
  }
});
