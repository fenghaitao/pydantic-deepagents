'use client';
import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { wikiService } from '@/services/wikiService';
import type { WikiContent as WikiContentType } from '@/lib/types';

interface Props {
  slug: string;
  repoPath?: string;
}

export default function WikiContent({ slug, repoPath }: Props) {
  const [page, setPage] = useState<WikiContentType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    setError('');
    setPage(null);
    wikiService.getContent(slug, repoPath ?? '')
      .then(setPage)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [slug, repoPath]);

  if (loading) return (
    <div className="flex items-center justify-center h-full text-zinc-500 text-sm">Loading…</div>
  );
  if (error) return (
    <div className="p-8 text-red-400 text-sm">
      <p className="font-semibold mb-1">Failed to load page</p>
      <pre className="text-xs text-zinc-500">{error}</pre>
    </div>
  );
  if (!page) return null;

  return (
    <article className="max-w-4xl mx-auto px-8 py-8 overflow-y-auto h-full">
      <p className="text-xs text-zinc-500 uppercase tracking-wide mb-1">{page.section}</p>
      <h1 className="text-2xl font-bold text-zinc-100 mb-6 pb-3 border-b border-zinc-800">{page.title}</h1>
      <div className="prose prose-invert prose-zinc max-w-none
        prose-h1:text-2xl prose-h2:text-xl prose-h2:border-b prose-h2:border-zinc-800 prose-h2:pb-1
        prose-h3:text-base prose-code:bg-zinc-800 prose-code:px-1 prose-code:rounded prose-code:text-emerald-300
        prose-pre:bg-zinc-900 prose-pre:border prose-pre:border-zinc-800
        prose-a:text-emerald-400 prose-blockquote:border-l-emerald-500
        prose-th:bg-zinc-800 prose-strong:text-zinc-100">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{page.content}</ReactMarkdown>
      </div>
    </article>
  );
}
