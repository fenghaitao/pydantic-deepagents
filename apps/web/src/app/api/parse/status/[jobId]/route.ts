import { NextRequest, NextResponse } from 'next/server';

const AGENT_URL = (process.env.AGENT_URL ?? 'http://localhost:8000').replace(/\/$/, '');

export async function GET(
  _req: NextRequest,
  { params }: { params: { jobId: string } },
) {
  const { jobId } = params;
  const res = await fetch(`${AGENT_URL}/parse/status/${jobId}`);
  const text = await res.text();
  let data: unknown;
  try { data = JSON.parse(text); } catch { data = { error: text }; }
  return NextResponse.json(data, { status: res.status });
}
