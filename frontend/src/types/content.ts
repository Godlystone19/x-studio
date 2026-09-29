export type ContentCategory = 'reference' | 'personal';

export interface DashboardOverview {
  reference_count: number;
  personal_count: number;
  generated_count: number;
  average_impressions: number | null;
  average_engagement_rate: number | null;
  likes: number;
  replies: number;
  reposts: number;
  bookmarks: number;
}

export interface ImportResult {
  inserted: number;
  skipped: number;
  category: ContentCategory;
}

export interface GeneratedPost {
  id: number;
  request_id: number;
  text: string;
  topic: string;
  format: string | null;
  tone: string | null;
  created_at: string;
  feedback: string | null;
  published: number;
  published_at: string | null;
  x_post_id: string | null;
  impressions: number | null;
  likes: number | null;
  replies: number | null;
  reposts: number | null;
  engagement_rate: number | null;
  originality: number;
  hook: string;
  char_count: number;
}

export interface GenerateOptions {
  topic: string;
  count: number;
  tone?: string;
  audience?: string;
  format?: string;
  length?: string;
  instructions?: string;
}

export interface GenerateResult {
  request_id: number;
  posts: Array<{ text: string }>;
  note: string;
}

export type Feedback = 'good' | 'bad' | 'rewrite' | 'save' | 'published' | 'high-performing' | 'low-performing';
