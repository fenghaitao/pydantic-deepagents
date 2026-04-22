'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import { ChevronDown, ChevronUp, ChevronRight, Loader2, BookOpen, RefreshCw } from 'lucide-react';
import { Project, WikiPage } from '@/lib/types';
import { listProjectsLocal, parseRepoLocal, getParseLocalStatus } from '@/services/projectService';
import { wikiService } from '@/services/wikiService';
import { clsx } from 'clsx';

interface Props {
  onSelectWikiPage: (slug: string, repoPath: string) => void;
  activeWikiSlug?: string | null;
  onProjectSelect?: (projectId: string) => void;
}

export default function Sidebar({ onSelectWikiPage, activeWikiSlug, onProjectSelect }: Props) {
  const [setupOpen, setSetupOpen] = useState(true);
  const [wikiOpen, setWikiOpen] = useState(false);

  // Repo & Agent setup
  const [repoPath, setRepoPath] = useState('');
  const [branch, setBranch] = useState('main');
  const [parseStatus, setParseStatus] = useState<'idle' | 'parsing' | 'done' | 'error'>('idle');
  const [parseMessage, setParseMessage] = useState('');

  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const hasAutoSelected = useRef(false);

  // Local map: projectId → repoPath, populated when user parses in this session
  // or carried from the projects list itself. Used as fallback when DB has no path.
  const repoPathCache = useRef<Record<string, string>>({});

  // Wiki
  const [wikiPages, setWikiPages] = useState<WikiPage[]>([]);
  const [wikiLoading, setWikiLoading] = useState(false);
  const [wikiOpenSections, setWikiOpenSections] = useState<Set<string>>(new Set());
  const [wikiGenerating, setWikiGenerating] = useState(false);
  const [wikiGenMsg, setWikiGenMsg] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const retryRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const parseTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadProjects = useCallback(async () => {
    try {
      const list = await listProjectsLocal();
      // Update the path cache from fresh project data
      for (const p of list) {
        if (p.repo_path) repoPathCache.current[p.id] = p.repo_path;
      }
      setProjects(list);
      if (list.length > 0 && !hasAutoSelected.current) {
        hasAutoSelected.current = true;
        setSelectedProjectId(list[0].id);
        onProjectSelect?.(list[0].id);
      }
      return list.length > 0;
    } catch {
      return false;
    }
  }, []);

  // On mount: load immediately, then retry every 3 s until agent is ready (max 20 s)
  useEffect(() => {
    loadProjects();
    let attempts = 0;
    retryRef.current = setInterval(async () => {
      attempts++;
      const got = await loadProjects();
      if (got || attempts >= 6) {
        clearInterval(retryRef.current!);
        retryRef.current = null;
      }
    }, 3000);
    return () => {
      if (retryRef.current) clearInterval(retryRef.current);
      if (pollRef.current) clearInterval(pollRef.current);
      if (parseTimeoutRef.current) clearTimeout(parseTimeoutRef.current);
    };
  }, [loadProjects]);

  const getRepoPath = useCallback((projectId: string): string | null => {
    // Try projects list first, then session cache
    const fromList = projects.find((p) => p.id === projectId)?.repo_path;
    if (fromList) return fromList;
    return repoPathCache.current[projectId] ?? null;
  }, [projects]);

  const loadWikiPages = useCallback(async (projectId: string) => {
    const rPath = getRepoPath(projectId);
    if (!rPath) return;
    setWikiLoading(true);
    setWikiPages([]);
    try {
      const pages = await wikiService.listPages(rPath);
      setWikiPages(pages);
      if (pages.length > 0) setWikiOpenSections(new Set([pages[0].section]));
    } catch { /* no wiki yet */ }
    finally { setWikiLoading(false); }
  }, [getRepoPath]);

  useEffect(() => {
    if (wikiOpen && selectedProjectId) loadWikiPages(selectedProjectId);
  }, [selectedProjectId, wikiOpen, loadWikiPages]);

  const handleWikiToggle = () => {
    setWikiOpen((v) => {
      if (!v && selectedProjectId) loadWikiPages(selectedProjectId);
      return !v;
    });
  };

  const handleGenerate = async () => {
    if (!selectedProjectId) return;
    const rPath = getRepoPath(selectedProjectId);
    if (!rPath) {
      setWikiGenMsg('Cannot find repo path. Parse this repo first using the inputs above.');
      return;
    }
    // Clear any existing poll before starting a new one
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    setWikiGenerating(true);
    setWikiGenMsg('Starting generation…');
    setWikiPages([]);
    try {
      const job = await wikiService.generateWiki(selectedProjectId, rPath);
      pollRef.current = setInterval(async () => {
        try {
          const s = await wikiService.getGenerateStatus(job.job_id);
          setWikiGenMsg(s.message);
          if (s.status === 'done') {
            clearInterval(pollRef.current!);
            setWikiGenerating(false);
            setWikiGenMsg('');
            await loadWikiPages(selectedProjectId);
          } else if (s.status === 'error') {
            clearInterval(pollRef.current!);
            setWikiGenerating(false);
            setWikiGenMsg(`Failed: ${s.message}`);
          }
        } catch { /* ignore poll errors */ }
      }, 3000);
    } catch (e) {
      setWikiGenerating(false);
      setWikiGenMsg(`Error: ${String(e)}`);
    }
  };

  const toggleWikiSection = (section: string) => {
    setWikiOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) { next.delete(section); } else { next.add(section); }
      return next;
    });
  };

  const handleParse = async () => {
    if (!repoPath.trim()) return;
    setParseStatus('parsing');
    setParseMessage('Submitting…');
    try {
      const { job_id } = await parseRepoLocal({ repo_path: repoPath.trim(), branch });
      setParseMessage('Parsing…');
      const poll = async () => {
        try {
          const job = await getParseLocalStatus(job_id);
          if (job.status === 'done') {
            const result = typeof job.result === 'object' ? job.result : {};
            const project_id = result?.project_id ?? '';
            setParseStatus('done');
            setParseMessage('Parsed successfully!');
            // Cache the repo path immediately so wiki works right away
            if (project_id && repoPath.trim()) {
              repoPathCache.current[project_id] = repoPath.trim();
            }
            await loadProjects();
            if (project_id) {
              hasAutoSelected.current = true;
              setSelectedProjectId(project_id);
              onProjectSelect?.(project_id);
            }
          } else if (job.status === 'error') {
            setParseStatus('error');
            const msg = typeof job.result === 'string' ? job.result : 'Parse failed.';
            setParseMessage(msg);
          } else {
            parseTimeoutRef.current = setTimeout(poll, 2000);
          }
        } catch {
          setParseStatus('error');
          setParseMessage('Failed to check status.');
        }
      };
      poll();
    } catch (e: unknown) {
      setParseStatus('error');
      setParseMessage(e instanceof Error ? e.message : 'Parse error');
    }
  };

  const selectedProject = projects.find((p) => p.id === selectedProjectId);
  const wikiSections = [...new Set(wikiPages.map((p) => p.section))];
  const wikiExists = wikiPages.length > 0;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b flex items-center gap-2">
        <span className="text-lg font-semibold tracking-tight">🪄 pydantic-deep</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Repo & Setup */}
        <div className="border-b">
          <button
            className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => setSetupOpen((v) => !v)}
          >
            <span>Repo & Setup</span>
            {setupOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>

          {setupOpen && (
            <div className="px-4 pb-4 flex flex-col gap-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Repo path</label>
                <input type="text"
                  className="w-full bg-muted rounded-lg px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  placeholder="/path/to/repo" value={repoPath} onChange={(e) => setRepoPath(e.target.value)} />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Branch</label>
                <input type="text"
                  className="w-full bg-muted rounded-lg px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  placeholder="main" value={branch} onChange={(e) => setBranch(e.target.value)} />
              </div>
              <button onClick={handleParse} disabled={!repoPath.trim() || parseStatus === 'parsing'}
                className="flex items-center justify-center gap-2 px-3 py-1.5 rounded-lg bg-secondary text-secondary-foreground text-sm font-medium hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                {parseStatus === 'parsing' && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Parse Repo
              </button>
              {parseMessage && (
                <p className={clsx('text-xs',
                  parseStatus === 'done' && 'text-green-400',
                  parseStatus === 'error' && 'text-red-400',
                  parseStatus === 'parsing' && 'text-muted-foreground')}>
                  {parseMessage}
                </p>
              )}

              {/* Projects dropdown — refreshes on click */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-muted-foreground">Active project</label>
                  <button onClick={() => loadProjects()}
                    className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                    title="Refresh projects list">
                    <RefreshCw className="w-3 h-3" />
                  </button>
                </div>
                <select
                  className="w-full bg-muted rounded-lg px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50"
                  value={selectedProjectId}
                  onFocus={() => loadProjects()}
                  onChange={(e) => {
                    setSelectedProjectId(e.target.value);
                    setWikiPages([]);
                    setWikiGenMsg('');
                    onProjectSelect?.(e.target.value);
                  }}>
                  {projects.length === 0
                    ? <option value="">— no projects yet —</option>
                    : projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.repo_name} ({p.branch_name})
                      </option>
                    ))}
                </select>
                {selectedProject && getRepoPath(selectedProjectId) && (
                  <p className="mt-1 text-[10px] text-zinc-500 truncate px-1" title={getRepoPath(selectedProjectId)!}>
                    {getRepoPath(selectedProjectId)}
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Wiki Section */}
        <div>
          <button
            className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            onClick={handleWikiToggle}
          >
            <span className="flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-emerald-400" />
              Wiki
              {wikiExists && !wikiOpen && (
                <span className="text-[10px] bg-emerald-900/60 text-emerald-400 px-1.5 py-0.5 rounded-full">
                  {wikiPages.length}
                </span>
              )}
            </span>
            {wikiOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>

          {wikiOpen && (
            <div className="pb-3">
              {selectedProject && (
                <p className="px-4 mb-2 text-xs text-zinc-500 truncate">
                  {selectedProject.repo_name}
                  <span className="text-zinc-600"> / {selectedProject.branch_name}</span>
                </p>
              )}

              {wikiLoading && (
                <div className="px-4 mb-2 flex items-center gap-2 text-xs text-zinc-500">
                  <Loader2 className="w-3 h-3 animate-spin" /> Loading…
                </div>
              )}

              {!selectedProjectId && !wikiLoading && (
                <p className="px-4 text-xs text-zinc-600">Select a project above first.</p>
              )}

              {selectedProjectId && !wikiLoading && !wikiExists && !wikiGenerating && (
                <div className="px-4 mb-2">
                  {!getRepoPath(selectedProjectId) ? (
                    <p className="text-xs text-amber-400 mb-2">
                      No local repo path for this project. Re-parse it using the inputs above to enable wiki generation.
                    </p>
                  ) : (
                    <>
                      <p className="text-xs text-zinc-600 mb-2">No wiki for this project yet.</p>
                      <button onClick={handleGenerate}
                        className="w-full flex items-center justify-center gap-2 text-sm py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-medium transition-colors">
                        <BookOpen className="w-3.5 h-3.5" />
                        Generate Wiki
                      </button>
                    </>
                  )}
                </div>
              )}

              {wikiGenerating && (
                <div className="px-4 mb-2">
                  <div className="flex items-center gap-2 text-xs text-zinc-400 mb-1">
                    <Loader2 className="w-3 h-3 animate-spin text-emerald-400" />
                    <span>Generating wiki…</span>
                  </div>
                  {wikiGenMsg && <p className="text-xs text-zinc-500 pl-5">{wikiGenMsg}</p>}
                  <p className="text-xs text-zinc-600 pl-5 mt-1">This may take a few minutes.</p>
                </div>
              )}

              {wikiGenMsg && !wikiGenerating && (
                <p className="px-4 text-xs text-red-400 mb-2">{wikiGenMsg}</p>
              )}

              {wikiSections.map((section) => (
                <div key={section}>
                  <button
                    className="w-full flex items-center gap-1.5 px-4 py-1 text-xs font-medium text-zinc-500 hover:text-zinc-300 uppercase tracking-wide"
                    onClick={() => toggleWikiSection(section)}
                  >
                    {wikiOpenSections.has(section)
                      ? <ChevronDown className="w-3 h-3" />
                      : <ChevronRight className="w-3 h-3" />}
                    {section}
                  </button>
                  {wikiOpenSections.has(section) && wikiPages
                    .filter((p) => p.section === section)
                    .map((page) => (
                      <button
                        key={page.slug}
                        onClick={() => onSelectWikiPage(page.slug, getRepoPath(selectedProjectId) ?? '')}
                        className={clsx(
                          'w-full text-left px-8 py-1.5 text-xs truncate transition-colors',
                          activeWikiSlug === page.slug
                            ? 'text-emerald-400 bg-emerald-950/40'
                            : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
                        )}
                      >
                        {page.title}
                      </button>
                    ))}
                </div>
              ))}

              {wikiExists && !wikiGenerating && (
                <div className="px-4 mt-2 pt-2 border-t border-zinc-800">
                  <button onClick={handleGenerate}
                    className="flex items-center gap-1.5 text-xs text-zinc-600 hover:text-zinc-400 transition-colors">
                    <RefreshCw className="w-3 h-3" /> Regenerate Wiki
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
