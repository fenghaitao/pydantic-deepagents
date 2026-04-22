import { apiFetch } from './apiClient';
import { Agent } from '../lib/types';

export async function listAgents(): Promise<Agent[]> {
  return apiFetch<Agent[]>('/list-available-agents');
}
