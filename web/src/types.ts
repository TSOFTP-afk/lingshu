export interface BookSummary {
  id: number;
  title: string;
  summary: string;
  category: string;
  sub_tags: string;
  cover_url: string;
  updated_at: string;
  chapter_count: number;
  word_count: number;
  latest_chapter_title: string | null;
}

export interface ChapterSummary {
  id: number;
  book_id: number;
  volume_title: string;
  title: string;
  outline: string;
  summary_text: string;
  sort_order: number;
  word_count: number;
  status?: string;
  published_at?: string;
  updated_at: string;
}

export interface ChapterDetail extends ChapterSummary {
  book_title: string;
  content: string;
  ai_probability: number;
  ai_probability_level: string;
  previous_chapter_id: number | null;
  next_chapter_id: number | null;
}

export interface BookshelfItem extends BookSummary {
  shelf_id: number | null;
  added_at: string;
  shelf_updated_at: string;
  first_chapter_id: number | null;
  first_chapter_title: string | null;
  latest_chapter_id: number | null;
  latest_chapter_title: string | null;
  latest_chapter_volume_title: string | null;
  latest_chapter_updated_at: string | null;
  last_chapter_id: number | null;
  last_chapter_title: string | null;
  last_chapter_volume_title: string | null;
  last_chapter_sort_order: number | null;
  last_chapter_index: number;
  progress_percent: number;
}

export interface BookshelfStatus {
  in_shelf: boolean;
  item: BookshelfItem | null;
}

export interface BookshelfShelf {
  id: number;
  user_id: number;
  name: string;
  is_default: number;
  book_count: number;
  created_at: string;
  updated_at: string;
}
