import { NextResponse } from 'next/server';

const AGENT_URL = (process.env.AGENT_URL ?? 'http://localhost:8000').replace(/\/$/, '');

export async function GET() {
  try {
    const res = await fetch(`${AGENT_URL}/projects`);
    const text = await res.text();
    let data: unknown;
    try { data = JSON.parse(text); } catch { data = { error: text }; }
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}
