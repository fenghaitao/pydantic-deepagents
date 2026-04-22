import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

const AGENT_URL = (process.env.AGENT_URL ?? 'http://localhost:8000').replace(/\/$/, '');

interface AgentProject {
  id: string;
  repo_name: string;
  branch_name: string;
  status: string;
  repo_path?: string | null;
}

/**
 * GET /api/wiki/repos
 * Fetches projects from the local agent (not the external Potpie backend),
 * then checks the local filesystem for .repowiki/en/content/ to set wiki_exists.
 */
export async function GET() {
  try {
    const res = await fetch(`${AGENT_URL}/projects`);
    if (!res.ok) {
      return NextResponse.json(
        { error: `Agent error: ${res.status}` },
        { status: res.status }
      );
    }

    const projects: AgentProject[] = await res.json();

    const repos = projects.map((p) => {
      const repoPath = p.repo_path ?? '';
      const contentRoot = repoPath
        ? path.join(repoPath, '.repowiki', 'en', 'content')
        : '';
      const wikiExists = contentRoot !== '' && fs.existsSync(contentRoot);

      return {
        project_id: p.id,
        repo_name: p.repo_name,
        branch_name: p.branch_name,
        status: p.status,
        repo_path: repoPath || null,
        wiki_exists: wikiExists,
      };
    });

    return NextResponse.json(repos);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}

