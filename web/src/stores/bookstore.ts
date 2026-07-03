import { defineStore } from 'pinia';
import { fetchBook, fetchBooks, fetchChapter, fetchChapters } from '../api';
import type { BookSummary, ChapterDetail, ChapterSummary } from '../types';

export const useBookstore = defineStore('bookstore', {
  state: () => ({
    books: [] as BookSummary[],
    currentBook: null as BookSummary | null,
    chapters: [] as ChapterSummary[],
    currentChapter: null as ChapterDetail | null,
    loading: false,
  }),
  actions: {
    async loadBooks(params: { q?: string; category?: string } = {}) {
      this.loading = true;
      try {
        this.books = await fetchBooks(params);
      } finally {
        this.loading = false;
      }
    },
    async loadBook(bookId: number) {
      this.loading = true;
      try {
        const [book, chapters] = await Promise.all([fetchBook(bookId), fetchChapters(bookId)]);
        this.currentBook = book;
        this.chapters = chapters;
      } finally {
        this.loading = false;
      }
    },
    async loadChapter(chapterId: number) {
      this.loading = true;
      try {
        this.currentChapter = await fetchChapter(chapterId);
      } finally {
        this.loading = false;
      }
    },
  },
});
