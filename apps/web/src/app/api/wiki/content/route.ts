import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

function slugToTitle(name: string) {
  return name.replace(/_/g, ' ');
}

export async function GET(req: NextRequest) {
  const repoPath = req.nextUrl.searchParams.get('repo_path');
  const slug = req.nextUrl.searchParams.get('slug');
  if (!repoPath || !slug) {
    return NextResponse.json({ error: 'repo_path and slug required' }, { status: 400 });
  }

  const contentRoot = path.resolve(path.join(repoPath, '.repowiki', 'en', 'content'));

  // Security: ensure the target stays inside contentRoot
  const target = path.resolve(path.join(contentRoot, slug) + '.md');
  if (!target.startsWith(contentRoot + path.sep) && target !== contentRoot) {
    return NextResponse.json({ error: 'Invalid slug' }, { status: 400 });
  }

  if (!fs.existsSync(target)) {
    return NextResponse.json({ error: `Page '${slug}' not found` }, { status: 404 });
  }

  const parts = slug.split('/');
  const section = parts.length > 1 ? slugToTitle(parts[0]) : '';
  const title = slugToTitle(path.basename(slug));
  const relativePath = path.relative(contentRoot, target);
  const content = fs.readFileSync(target, 'utf-8');

  return NextResponse.json({ title, section, slug, path: relativePath, content });
}
