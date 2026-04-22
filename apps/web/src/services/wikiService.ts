import type { WikiRepo, WikiPage, WikiContent, WikiJobStatus } from '@/lib/types';

export const wikiService = {
  // Local Next.js route — no longer depends on wiki_router.py
  async listRepos(): Promise<WikiRepo[]> {
    const res = await fetch('/api/wiki/repos');
    if (!res.ok) return [];
    return res.json();
  },

  // Local Next.js routes — read directly from filesystem
  async listPages(repoPath: string): Promise<WikiPage[]> {
    const res = await fetch(`/api/wiki/pages?repo_path=${encodeURIComponent(repoPath)}`);
    if (!res.ok) return [];
    return res.json();
  },

  async getContent(slug: string, repoPath: string): Promise<WikiContent> {
    const res = await fetch(
      `/api/wiki/content?repo_path=${encodeURIComponent(repoPath)}&slug=${encodeURIComponent(slug)}`
    );
    if (!res.ok) throw new Error(`Failed to load wiki page: ${res.status}`);
    return res.json();
  },

  async generateWiki(projectId: string, repoPath: string): Promise<WikiJobStatus> {
    const res = await fetch('/api/wiki/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, repo_path: repoPath }),
    });
    if (!res.ok) throw new Error(`Generate failed: ${res.status}`);
    return res.json();
  },

  async getGenerateStatus(jobId: string): Promise<WikiJobStatus> {
    const res = await fetch(`/api/wiki/generate/status/${jobId}`);
    if (!res.ok) throw new Error(`Status check failed: ${res.status}`);
    return res.json();
  },
};
