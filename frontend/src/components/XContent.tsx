import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { BarChart3, LoaderCircle, Sparkles } from 'lucide-react';
import { generatePosts, getGeneratedPosts, getOverview, saveFeedback } from '../api/client';
import type { DashboardOverview, Feedback, GeneratedPost, GenerateOptions, ImportResult } from '../types/content';
import { DraftCard } from './DraftCard';
import { ImportControl } from './ImportControl';
import { MetricCard } from './MetricCard';

type Notice = { kind: 'success' | 'error' | 'info'; text: string } | null;

const emptyOverview: DashboardOverview = {
  reference_count: 0,
  personal_count: 0,
  generated_count: 0,
  average_impressions: null,
  average_engagement_rate: null,
  likes: 0,
  replies: 0,
  reposts: 0,
  bookmarks: 0,
};

function toMetric(value: number | null, digits = 0): string {
  return value == null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function XContent() {
  const [overview, setOverview] = useState(emptyOverview);
  const [posts, setPosts] = useState<GeneratedPost[]>([]);
  const [topic, setTopic] = useState('');
  const [count, setCount] = useState(5);
  const [tone, setTone] = useState('');
  const [audience, setAudience] = useState('');
  const [format, setFormat] = useState('');
  const [length, setLength] = useState('');
  const [instructions, setInstructions] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<Notice>(null);

  const refresh = useCallback(async () => {
    const [dashboard, drafts] = await Promise.all([getOverview(), getGeneratedPosts()]);
    setOverview(dashboard);
    setPosts(drafts);
  }, []);

  useEffect(() => {
    let active = true;
    Promise.all([getOverview(), getGeneratedPosts()])
      .then(([dashboard, drafts]) => {
        if (!active) return;
        setOverview(dashboard);
        setPosts(drafts);
      })
      .catch((error: unknown) => {
        if (active) setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Could not load your content data.' });
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  function handleImport(result: ImportResult) {
    setNotice({ kind: 'success', text: `${result.inserted} imported · ${result.skipped} skipped or duplicate` });
    void refresh().catch((error: unknown) => setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Import completed, but the dashboard could not refresh.' }));
  }

  async function submitGeneration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const options: GenerateOptions = {
      topic: topic.trim(),
      count,
      tone: tone.trim() || undefined,
      audience: audience.trim() || undefined,
      format: format || undefined,
      length: length || undefined,
      instructions: instructions.trim() || undefined,
    };
    if (!options.topic) {
      setNotice({ kind: 'error', text: 'Add a topic before generating posts.' });
      return;
    }

    setBusy(true);
    setNotice({ kind: 'info', text: 'Generating drafts…' });
    try {
      const result = await generatePosts(options);
      try {
        await refresh();
      } catch (refreshErr) {
        console.warn('Dashboard refresh failed after generation:', refreshErr);
      }
      setNotice({
        kind: result.posts.length ? 'success' : 'info',
        text: result.posts.length ? result.note : 'No drafts passed the originality screen. Try another angle or request.',
      });
    } catch (error) {
      setNotice({ kind: 'error', text: error instanceof Error ? error.message : 'Generation failed. Try again.' });
    } finally {
      setBusy(false);
    }
  }

  async function handleFeedback(id: number, feedback: Feedback) {
    try {
      await saveFeedback(id, feedback);
      await refresh();
      setNotice({ kind: 'success', text: `Feedback saved: ${feedback}.` });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not save feedback.';
      setNotice({ kind: 'error', text: message });
      throw error;
    }
  }

  function importError(message: string) {
    setNotice({ kind: 'error', text: message });
  }

  const metrics = [
    { label: 'Reference library', value: toMetric(overview.reference_count), detail: 'Style examples' },
    { label: 'Personal posts', value: toMetric(overview.personal_count), detail: 'Account history' },
    { label: 'Generated drafts', value: toMetric(overview.generated_count), detail: 'Saved in this workspace', highlight: true },
    { label: 'Avg impressions', value: toMetric(overview.average_impressions), detail: 'Personal posts with data' },
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-8 sm:space-y-10">
      <header className="flex flex-col gap-5 border-b border-border pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-[.2em] text-muted">Creator workspace / 01</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">X Content Studio</h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
            Generate original posts informed by your examples and account history. Performance indicators describe patterns, never guarantees.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ImportControl category="reference" label="Import examples" onComplete={handleImport} onError={importError} />
          <ImportControl category="personal" label="Import my posts" onComplete={handleImport} onError={importError} />
        </div>
      </header>

      {notice && (
        <div
          role={notice.kind === 'error' ? 'alert' : 'status'}
          aria-live="polite"
          className={`rounded-lg border px-4 py-3 text-sm ${notice.kind === 'error' ? 'border-charcoal bg-surface text-foreground' : notice.kind === 'success' ? 'border-accent/40 bg-accent/10 text-accent' : 'border-border bg-surface text-muted'}`}
        >
          {notice.kind === 'error' && <strong className="mr-1">Error:</strong>}
          {notice.text}
        </div>
      )}

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Account overview">
        {metrics.map((metric) => <MetricCard key={metric.label} {...metric} />)}
      </section>

      <div className="grid items-start gap-5 lg:grid-cols-[.9fr_1.1fr]">
        <form onSubmit={submitGeneration} className="space-y-4 rounded-xl border border-border bg-surface/50 p-5 sm:p-6">
          <div className="flex items-center gap-2 text-foreground">
            <Sparkles size={16} className="text-accent" aria-hidden="true" />
            <h2 className="font-medium">Generate posts</h2>
          </div>

          <label className="block text-xs text-muted">
            Topic <span className="text-muted">(required)</span>
            <input
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              required
              maxLength={180}
              className="mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-foreground outline-none transition-colors placeholder:text-muted focus:border-accent"
              placeholder="e.g. forex market structure"
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs text-muted">
              Number of posts
              <select value={count} onChange={(event) => setCount(Number(event.target.value))} className="mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-foreground focus:border-accent">
                {[1, 3, 5, 10, 15, 20].map((number) => <option key={number} value={number}>{number}</option>)}
              </select>
            </label>
            <label className="text-xs text-muted">
              Tone
              <input value={tone} onChange={(event) => setTone(event.target.value)} maxLength={80} className="mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-foreground placeholder:text-muted focus:border-accent" placeholder="Use my profile" />
            </label>
            <label className="text-xs text-muted">
              Audience
              <input value={audience} onChange={(event) => setAudience(event.target.value)} maxLength={120} className="mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-foreground placeholder:text-muted focus:border-accent" placeholder="e.g. new traders" />
            </label>
            <label className="text-xs text-muted">
              Format
              <select value={format} onChange={(event) => setFormat(event.target.value)} className="mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-foreground focus:border-accent">
                <option value="">Choose for me</option><option value="single post">Single post</option><option value="thread">Thread</option><option value="list">List</option><option value="question">Question</option>
              </select>
            </label>
          </div>

          <label className="block text-xs text-muted">
            Post length
            <select value={length} onChange={(event) => setLength(event.target.value)} className="mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-foreground focus:border-accent">
              <option value="">Choose for me</option><option value="short">Short and concise</option><option value="medium">Medium</option><option value="long">Long-form</option>
            </select>
          </label>

          <label className="block text-xs text-muted">
            Extra direction <span className="text-muted">(optional)</span>
            <textarea value={instructions} onChange={(event) => setInstructions(event.target.value)} maxLength={1000} rows={3} className="mt-1.5 w-full resize-y rounded-lg border border-border bg-surface px-3 py-2.5 text-sm text-foreground placeholder:text-muted focus:border-accent" placeholder="Include a particular angle, question, or call to action…" />
          </label>

          <button disabled={busy || !topic.trim()} className="flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-background transition-[filter,transform] hover:brightness-110 active:scale-[.99] disabled:cursor-not-allowed disabled:opacity-60">
            {busy ? <LoaderCircle className="animate-spin" size={15} aria-hidden="true" /> : <Sparkles size={15} aria-hidden="true" />}
            {busy ? 'Writing…' : 'Generate drafts'}
          </button>
          <p className="border-t border-border pt-3 text-[11px] leading-relaxed text-muted">LLM credentials stay on the backend. Set LLM_API_KEY there to enable generation.</p>
        </form>

        <section aria-labelledby="drafts-heading" className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 id="drafts-heading" className="font-medium text-foreground">Recent drafts</h2>
              <p className="mt-1 text-xs text-muted">Saved drafts and their review indicators</p>
            </div>
            <span className="rounded-full border border-border px-2.5 py-1 text-xs text-muted">{toMetric(overview.generated_count)} total</span>
          </div>
          {loading ? (
            <div className="flex min-h-36 items-center justify-center gap-2 rounded-xl border border-border text-sm text-muted"><LoaderCircle size={16} className="animate-spin" aria-hidden="true" /> Loading drafts…</div>
          ) : posts.length === 0 ? (
            <div className="rounded-xl border border-dashed border-charcoal p-8 text-center">
              <Sparkles size={20} className="mx-auto text-muted" aria-hidden="true" />
              <p className="mt-3 text-sm font-medium text-foreground">Your drafts will appear here</p>
              <p className="mt-1 text-xs text-muted">Add a topic and generate your first set of posts.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {posts.map((post) => <DraftCard key={post.id} post={post} onFeedback={handleFeedback} />)}
            </div>
          )}
        </section>
      </div>

      <aside className="flex items-start gap-3 rounded-xl border border-border bg-surface/30 p-4 text-xs leading-relaxed text-muted">
        <BarChart3 size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
        <p>Performance patterns are descriptive and do not establish cause. Missing metrics remain missing. Originality is estimated with text comparison, not semantic analysis. Current news and automatic X publishing are not connected in this MVP; verify facts before posting.</p>
      </aside>
    </div>
  );
}
