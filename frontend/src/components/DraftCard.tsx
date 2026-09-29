import { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import type { Feedback, GeneratedPost } from '../types/content';

interface DraftCardProps {
  post: GeneratedPost;
  onFeedback: (id: number, feedback: Feedback) => Promise<void>;
}

export function DraftCard({ post, onFeedback }: DraftCardProps) {
  const [copied, setCopied] = useState(false);
  const [saving, setSaving] = useState(false);

  async function copyPost() {
    try {
      await navigator.clipboard.writeText(post.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be disabled by browser permissions.
    }
  }

  async function submitFeedback(feedback: Feedback) {
    setSaving(true);
    try {
      await onFeedback(post.id, feedback);
    } catch {
      // The parent reports the API error to the workspace status region.
    } finally {
      setSaving(false);
    }
  }

  const badges = [post.hook, post.format || 'single post', `${post.char_count} chars`, `Lexical originality ${Math.round(post.originality * 100)}%`];

  return (
    <article className="rounded-xl border border-border bg-surface p-4 shadow-subtle">
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-foreground">{post.text}</p>
      <div className="mt-4 flex flex-wrap gap-2" aria-label="Post indicators">
        {badges.map((badge) => (
          <span key={badge} className="rounded bg-background px-2 py-1 text-[10px] text-muted">{badge}</span>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
        <div className="flex flex-wrap gap-3">
          {(['good', 'save', 'published'] as const).map((feedback) => (
            <button
              key={feedback}
              type="button"
              disabled={saving}
              aria-pressed={post.feedback === feedback}
              onClick={() => void submitFeedback(feedback)}
              className={`text-xs capitalize transition-colors hover:text-foreground disabled:opacity-50 ${post.feedback === feedback ? 'font-semibold text-accent' : 'text-muted'}`}
            >
              {feedback}
            </button>
          ))}
        </div>
        <button type="button" onClick={() => void copyPost()} className={`inline-flex items-center gap-1 text-xs ${copied ? 'text-accent' : 'text-muted hover:text-foreground'}`} aria-label="Copy draft text">
          {copied ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
    </article>
  );
}
