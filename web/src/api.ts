import axios from 'axios';
import type { BookSummary, BookshelfItem, BookshelfShelf, BookshelfStatus, ChapterDetail, ChapterSummary } from './types';

export const api = axios.create({
  baseURL: '/api',
  timeout: 8000,
});

export async function fetchBooks(params: { q?: string; category?: string } = {}) {
  const { data } = await api.get<{ items: BookSummary[] }>('/books', { params });
  return data.items;
}

export async function fetchBook(bookId: number) {
  const { data } = await api.get<BookSummary>(`/books/${bookId}`);
  return data;
}

export async function fetchChapters(bookId: number) {
  const { data } = await api.get<{ items: ChapterSummary[] }>(`/books/${bookId}/chapters`);
  return data.items;
}

export async function fetchChapter(chapterId: number) {
  const { data } = await api.get<ChapterDetail>(`/chapters/${chapterId}`);
  return data;
}

function authConfig(token: string) {
  return { headers: { Authorization: `Bearer ${token}` } };
}

export async function fetchBookshelf(token: string, shelfId?: number | null) {
  const { data } = await api.get<{ items: BookshelfItem[] }>('/bookshelf', {
    ...authConfig(token),
    params: shelfId ? { shelf_id: shelfId } : undefined,
  });
  return data.items;
}

export async function fetchBookshelfShelves(token: string) {
  const { data } = await api.get<{ items: BookshelfShelf[] }>('/bookshelf/shelves', authConfig(token));
  return data.items;
}

export async function createBookshelfShelf(name: string, token: string) {
  const { data } = await api.post<{ ok: boolean; item: BookshelfShelf }>('/bookshelf/shelves', { name }, authConfig(token));
  return data.item;
}

export async function fetchBookshelfStatus(bookId: number, token: string) {
  const { data } = await api.get<BookshelfStatus>(`/bookshelf/${bookId}`, authConfig(token));
  return data;
}

export async function addBookshelfItem(bookId: number, token: string) {
  const { data } = await api.put<{ ok: boolean; item: BookshelfItem }>(`/bookshelf/${bookId}`, {}, authConfig(token));
  return data.item;
}

export async function removeBookshelfItem(bookId: number, token: string) {
  const { data } = await api.delete<{ ok: boolean }>(`/bookshelf/${bookId}`, authConfig(token));
  return data;
}

export async function updateBookshelfProgress(bookId: number, chapterId: number, token: string) {
  const { data } = await api.patch<{ ok: boolean; item: BookshelfItem }>(
    `/bookshelf/${bookId}/progress`,
    { chapter_id: chapterId },
    authConfig(token),
  );
  return data.item;
}
