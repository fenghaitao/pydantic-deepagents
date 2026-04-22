import { apiFetch } from './apiClient';
import { Project, ParseRequest } from '../lib/types';

export async function listProjects(): Promise<Project[]> {
  return apiFetch<Project[]>('/projects/list');
}

/** List projects from the local agent (not the external Potpie backend). */
export async function listProjectsLocal(): Promise<Project[]> {
  const res = await fetch('/api/projects');
  if (!res.ok) return [];
  const data = await res.json();
  // Agent returns array; guard against error object
  if (!Array.isArray(data)) return [];
  return data.map((p: {id: string; repo_name: string; branch_name: string; status: string; repo_path?: string}) => ({
    id: p.id,
    repo_name: p.repo_name,
    branch_name: p.branch_name,
    status: p.status,
    repo_path: p.repo_path ?? '',
  }));
}

export async function parseRepo(req: ParseRequest): Promise<{ project_id: string }> {
  return apiFetch<{ project_id: string }>('/parse', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export async function getParsingStatus(projectId: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/parsing-status/${projectId}`);
}

/** Start a local parse job via the local agent (not the external Potpie backend). */
export async function parseRepoLocal(req: { repo_path: string; branch: string }): Promise<{ job_id: string; status: string }> {
  const res = await fetch('/api/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Parse error ${res.status}: ${await res.text()}`);
  return res.json();
}

/** Poll the status of a local parse job. */
export async function getParseLocalStatus(jobId: string): Promise<{
  status: 'started' | 'done' | 'error';
  result?: { project_id?: string; status?: string; message?: string } | string;
  error?: string;
}> {
  const res = await fetch(`/api/parse/status/${jobId}`);
  if (!res.ok) throw new Error(`Status error ${res.status}: ${await res.text()}`);
  return res.json();
}

