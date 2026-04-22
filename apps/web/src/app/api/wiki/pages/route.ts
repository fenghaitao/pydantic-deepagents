import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

function slugToTitle(name: string) {
  return name.replace(/_/g, ' ');
}

interface WikiPage {
  title: string;
  section: string;
  slug: string;
  path: string;
}

// Parse wiki_structure.xml manually (no external parser needed)
function pagesFromXml(xmlPath: string, contentRoot: string): WikiPage[] | null {
  try {
    const xml = fs.readFileSync(xmlPath, 'utf-8');

    // Extract page id→title map
    const pageTitles: Record<string, string> = {};
    const pageRe = /<page\s+id="([^"]+)"[^>]*>[\s\S]*?<title>([\s\S]*?)<\/title>/g;
    let m: RegExpExecArray | null;
    while ((m = pageRe.exec(xml)) !== null) {
      pageTitles[m[1].trim()] = m[2].trim();
    }

    // Extract section id→title map
    const sectionTitles: Record<string, string> = {};
    const secRe = /<section\s+id="([^"]+)"[^>]*>[\s\S]*?<title>([\s\S]*?)<\/title>/g;
    while ((m = secRe.exec(xml)) !== null) {
      sectionTitles[m[1].trim()] = m[2].trim();
    }

    // Walk sections in document order and collect page_refs
    const pages: WikiPage[] = [];
    const seen = new Set<string>();
    const secBlockRe = /<section\s+id="([^"]+)"[\s\S]*?<\/section>/g;
    while ((m = secBlockRe.exec(xml)) !== null) {
      const secId = m[1].trim();
      const secLabel = sectionTitles[secId] ?? slugToTitle(secId);
      const block = m[0];
      const refRe = /<page_ref>([\s\S]*?)<\/page_ref>/g;
      let r: RegExpExecArray | null;
      while ((r = refRe.exec(block)) !== null) {
        const pid = r[1].trim();
        const pageTitle = pageTitles[pid];
        if (!pageTitle) continue;
        // Find matching .md file by page title
        const found = findMdFile(contentRoot, pageTitle);
        if (!found) continue;
        const { sectionDir, stem } = found;
        const slug = `${sectionDir}/${stem}`;
        if (seen.has(slug)) continue;
        seen.add(slug);
        pages.push({ title: pageTitle, section: secLabel, slug, path: `${sectionDir}/${stem}.md` });
      }
    }
    return pages.length > 0 ? pages : null;
  } catch {
    return null;
  }
}

function findMdFile(contentRoot: string, title: string): { sectionDir: string; stem: string } | null {
  const needle = title.toLowerCase().replace(/\s+/g, '_');
  try {
    for (const sectionDir of fs.readdirSync(contentRoot)) {
      const sectionPath = path.join(contentRoot, sectionDir);
      if (!fs.statSync(sectionPath).isDirectory()) continue;
      for (const file of fs.readdirSync(sectionPath)) {
        if (!file.endsWith('.md')) continue;
        const stem = file.slice(0, -3);
        if (stem.toLowerCase() === needle || stem.toLowerCase().replace(/\s+/g, '_') === needle) {
          return { sectionDir, stem };
        }
      }
    }
  } catch { /* ignore */ }
  return null;
}

function pagesFromDirs(contentRoot: string): WikiPage[] {
  const pages: WikiPage[] = [];
  try {
    for (const sectionDir of fs.readdirSync(contentRoot).sort()) {
      const sectionPath = path.join(contentRoot, sectionDir);
      if (!fs.statSync(sectionPath).isDirectory()) continue;
      const section = slugToTitle(sectionDir);
      for (const file of fs.readdirSync(sectionPath).sort()) {
        if (!file.endsWith('.md')) continue;
        const stem = file.slice(0, -3);
        pages.push({
          title: slugToTitle(stem),
          section,
          slug: `${sectionDir}/${stem}`,
          path: `${sectionDir}/${file}`,
        });
      }
    }
  } catch { /* ignore */ }
  return pages;
}

export async function GET(req: NextRequest) {
  const repoPath = req.nextUrl.searchParams.get('repo_path');
  if (!repoPath) return NextResponse.json({ error: 'repo_path required' }, { status: 400 });

  const contentRoot = path.join(repoPath, '.repowiki', 'en', 'content');
  if (!fs.existsSync(contentRoot)) return NextResponse.json([]);

  const xmlPath = path.join(repoPath, '.repowiki', 'wiki_structure.xml');
  const pages = (fs.existsSync(xmlPath) ? pagesFromXml(xmlPath, contentRoot) : null)
    ?? pagesFromDirs(contentRoot);

  return NextResponse.json(pages);
}
