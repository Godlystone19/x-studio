import type {
  ContentCategory,
  DashboardOverview,
  Feedback,
  GeneratedPost,
  GenerateOptions,
  GenerateResult,
  ImportResult,
} from '../types/content';

const API_BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/content${path}`, init);
  } catch {
    throw new Error('Could not reach the X Content API. Check that the backend is running.');
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string | Array<{ msg?: string }> | Record<string, unknown> } | null;
    let message = `Request failed (${response.status}).`;
    if (typeof body?.detail === 'string') {
      message = body.detail;
    } else if (Array.isArray(body?.detail)) {
      message = body.detail.map((err) => (typeof err === 'object' && err?.msg ? err.msg : JSON.stringify(err))).join(', ');
    } else if (body?.detail) {
      message = JSON.stringify(body.detail);
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function jsonRequest<T>(path: string, payload: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export const getOverview = () => request<DashboardOverview>('/overview');
export const getGeneratedPosts = () => request<GeneratedPost[]>('/generated');
export const generatePosts = (options: GenerateOptions) => jsonRequest<GenerateResult>('/generate', options);

export function importPosts(category: ContentCategory, filename: string, content: string, encoding: 'text' | 'base64') {
  return jsonRequest<ImportResult>('/import', { category, filename, content, encoding });
}

export function saveFeedback(id: number, feedback: Feedback) {
  return jsonRequest<{ ok: boolean }>(`/generated/${id}/feedback`, { feedback });
}
