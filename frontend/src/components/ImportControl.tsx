import { useRef, useState } from 'react';
import { ArrowUpFromLine, LoaderCircle } from 'lucide-react';
import { importPosts } from '../api/client';
import type { ContentCategory, ImportResult } from '../types/content';

interface ImportControlProps {
  category: ContentCategory;
  label: string;
  onComplete: (result: ImportResult) => void;
  onError: (message: string) => void;
}

const MAX_FILE_SIZE = 7.5 * 1024 * 1024;

async function readFile(file: File): Promise<{ content: string; encoding: 'text' | 'base64' }> {
  if (!/\.xlsx?$/i.test(file.name)) return { content: await file.text(), encoding: 'text' };

  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return { content: btoa(binary), encoding: 'base64' };
}

export function ImportControl({ category, label, onComplete, onError }: ImportControlProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  async function handleFile(file?: File) {
    if (!file) return;
    if (file.size > MAX_FILE_SIZE) {
      onError('Choose a file smaller than 7.5 MB.');
      return;
    }

    setBusy(true);
    try {
      const { content, encoding } = await readFile(file);
      const result = await importPosts(category, file.name, content, encoding);
      onComplete(result);
    } catch (error) {
      onError(error instanceof Error ? error.message : 'The file could not be imported.');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.json,.jsonl,.txt,.xls,.xlsx"
        className="sr-only"
        aria-label={`Choose ${label} file`}
        onChange={(event) => void handleFile(event.target.files?.[0])}
      />
      <button
        type="button"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-charcoal bg-surface px-3 py-2 text-xs text-foreground transition-colors hover:border-accent hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-60"
      >
        {busy ? <LoaderCircle size={14} className="animate-spin" aria-hidden="true" /> : <ArrowUpFromLine size={14} aria-hidden="true" />}
        {busy ? 'Importing…' : label}
      </button>
    </>
  );
}
