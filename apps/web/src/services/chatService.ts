import { apiFetch, USER_ID } from './apiClient';
import { Conversation } from '../lib/types';

export async function createConversation(
  projectId: string,
  agentId: string,
  title = 'New Chat'
): Promise<Conversation> {
  const data = await apiFetch<{ conversation_id: string; message?: string }>('/conversations', {
    method: 'POST',
    body: JSON.stringify({
      user_id: USER_ID,
      title,
      status: 'active',
      project_ids: [projectId],
      agent_ids: [agentId],
    }),
  });
  return { id: data.conversation_id, title, status: 'active', agent_ids: [agentId], project_ids: [projectId] };
}
