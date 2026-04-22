import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from '@copilotkit/runtime';
import { HttpAgent } from '@ag-ui/client';
import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

function getAgentUrl(): string {
  // Always read .env.local first — agent start.py writes AGENT_URL there at
  // runtime and may change the port on restart.
  try {
    const envPath = path.resolve(process.cwd(), '.env.local');
    const content = fs.readFileSync(envPath, 'utf8');
    const match = content.match(/^AGENT_URL=(.+)$/m);
    if (match) return match[1].trim();
  } catch { /* file may not exist yet */ }

  // Fall back to process.env (set at Next.js startup from .env.local)
  if (process.env.AGENT_URL) return process.env.AGENT_URL;

  return 'http://localhost:8000/';
}

function createHandler() {
  const url = getAgentUrl();
  const runtime = new CopilotRuntime({
    agents: {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      pydantic_deep_agent: new HttpAgent({ url }) as any,
    },
  });
  return copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter: new ExperimentalEmptyAdapter(),
    endpoint: '/api/copilotkit',
  }).handleRequest;
}

// Re-create handler on each request to pick up port changes from agent restarts
async function handler(req: NextRequest) {
  try {
    const handleRequest = createHandler();
    return await handleRequest(req);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.stack ?? e.message : String(e);
    console.error('[copilotkit]', msg);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

export const GET = handler;
export const POST = handler;
export const OPTIONS = handler;
