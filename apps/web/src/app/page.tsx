'use client';
import { useCoAgent } from '@copilotkit/react-core';
import { CopilotSidebar } from '@copilotkit/react-ui';
import Sidebar from '@/components/Sidebar';
import WikiContent from '@/components/WikiContent';
import { useState } from 'react';

interface PotpieState {
  project_id: string | null;
  agent_id: string;
  last_response: string | null;
}

const initialState: PotpieState = {
  project_id: null,
  agent_id: 'codebase_qna_agent',
  last_response: null,
};

export default function Home() {
  const [activeWikiSlug, setActiveWikiSlug] = useState<string | null>(null);
  const [activeWikiRepoPath, setActiveWikiRepoPath] = useState<string | null>(null);

  // setState lets us push project_id into the CopilotKit AG-UI state so that
  // WebPotpieCapability.before_run() can read it and set kg_context for KG tools.
  const { setState } = useCoAgent<PotpieState>({ name: 'pydantic_deep_agent', initialState });

  // Called by Sidebar whenever the user selects a different project.
  // Syncing project_id into CopilotKit state means the very next chat message
  // will already have the correct project wired up for all KG tool calls.
  const handleProjectSelect = (projectId: string) => {
    setState((prev) => ({ ...prev, project_id: projectId }));
  };

  const handleSelectWikiPage = (slug: string, repoPath: string) => {
    setActiveWikiSlug(slug);
    setActiveWikiRepoPath(repoPath);
  };

  return (
    <div className="flex h-screen bg-background text-foreground">
      <div className="w-72 border-r flex-shrink-0">
        <Sidebar
          onSelectWikiPage={handleSelectWikiPage}
          activeWikiSlug={activeWikiSlug}
          onProjectSelect={handleProjectSelect}
        />
      </div>
      <div className="flex-1 overflow-hidden">
        {activeWikiSlug ? (
          <WikiContent slug={activeWikiSlug} repoPath={activeWikiRepoPath ?? undefined} />
        ) : (
          <div className="flex flex-col h-full items-center justify-center text-muted-foreground gap-2">
            <p className="text-lg">Welcome to pydantic-deep</p>
            <p className="text-sm opacity-60">Select a wiki page, or use the chat panel on the right →</p>
          </div>
        )}
      </div>
      <CopilotSidebar
        defaultOpen={false}
        clickOutsideToClose={false}
        disableSystemMessage={true}
        onSetOpen={() => {}}
        labels={{
          title: 'pydantic-deep',
          initial: '👋 Hi! Ask me to parse a repo, list projects, or chat with your codebase.',
        }}
        suggestions={[
          { title: 'List projects', message: 'List my parsed projects.' },
          { title: 'Parse repo', message: 'Parse the repo at /path/to/my/repo on branch main.' },
          { title: 'Ask codebase', message: 'What does the authentication module do?' },
        ]}
      />
    </div>
  );
}
