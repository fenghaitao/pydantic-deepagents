import { NextRequest, NextResponse } from 'next/server';
import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';
import crypto from 'crypto';
import { setJob } from './jobStore';

// Resolve paths relative to apps/web (process.cwd() when Next.js runs)
// apps/web → apps → pydantic-deep (parents[2])
const _WEB_DIR = process.cwd(); // apps/web
const _REPO_ROOT = path.resolve(_WEB_DIR, '..', '..'); // pydantic-deep/

const WIKI_SCRIPT = process.env.WIKI_SCRIPT
  ?? path.join(
    _REPO_ROOT,
    'code-graph-providers', 'potpie',
    '.kiro', 'skills', 'deepwiki-open-wiki', 'scripts', 'generate_deepwiki.py',
  );

// Run from the potpie sub-repo so the script's own sys.path bootstrap works
const WIKI_CWD = process.env.WIKI_CWD
  ?? path.join(_REPO_ROOT, 'code-graph-providers', 'potpie');

// Use the potpie venv python (has all wiki dependencies)
const WIKI_PYTHON = process.env.WIKI_PYTHON
  ?? path.join(WIKI_CWD, '.venv', 'bin', 'python');

export async function POST(req: NextRequest) {
  const { project_id, repo_path } = await req.json();
  if (!repo_path) return NextResponse.json({ error: 'repo_path required' }, { status: 400 });

  // Validate repo_path: must exist, be a directory, and contain a .git folder.
  const resolvedPath = path.resolve(repo_path as string);
  if (
    !fs.existsSync(resolvedPath) ||
    !fs.statSync(resolvedPath).isDirectory() ||
    !fs.existsSync(path.join(resolvedPath, '.git'))
  ) {
    return NextResponse.json(
      { error: `repo_path must be an existing git repository: ${resolvedPath}` },
      { status: 422 },
    );
  }

  const jobId = crypto.randomUUID();
  setJob(jobId, { status: 'running', message: 'Starting wiki generation…' });

  const args = [WIKI_SCRIPT, '--repo_path', resolvedPath];
  if (project_id) args.push('--project_id', project_id);

  const child = spawn(WIKI_PYTHON, args, {
    cwd: WIKI_CWD,
    // Drain stdout to prevent the pipe from filling and deadlocking the child.
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  // Consume stdout (discarded — wiki output goes to files, not stdout)
  child.stdout?.resume();

  let stderr = '';
  child.stderr?.on('data', (d: Buffer) => { stderr += d.toString(); });

  child.on('close', (code) => {
    if (code === 0) {
      setJob(jobId, { status: 'done', message: 'Wiki generated successfully!' });
    } else {
      setJob(jobId, { status: 'error', message: (stderr || 'Unknown error').slice(-600) });
    }
  });

  child.on('error', (err) => {
    setJob(jobId, { status: 'error', message: err.message });
  });

  return NextResponse.json({ job_id: jobId, status: 'running', message: 'Wiki generation started' });
}

