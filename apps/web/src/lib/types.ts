export interface Project {
  id: string;
  repo_name: string;
  branch_name: string;
  status: string;
  repo_path?: string;
}

export interface Agent {
  id: string;
  name: string;
  description?: string;
}

export interface Conversation {
  id: string;
  title: string;
  status: string;
  agent_ids: string[];
  project_ids: string[];
}

export interface WikiRepo {
  project_id: string;
  repo_name: string;
  branch_name: string;
  status: string;
  repo_path: string | null;
  wiki_exists: boolean;
}

export interface WikiPage {
  title: string;
  section: string;
  slug: string;
  path: string;
}

export interface WikiContent {
  title: string;
  content: string;
  slug: string;
}

export interface WikiJobStatus {
  job_id: string;
  status: 'running' | 'done' | 'error';
  message: string;
}

export interface ParseRequest {
  repo_path: string;
  branch_name: string;
}
