import { NextRequest, NextResponse } from 'next/server';
import { getJob } from '../../jobStore';

export async function GET(
  _req: NextRequest,
  { params }: { params: { jobId: string } }
) {
  const { jobId } = params;
  const job = getJob(jobId);
  if (!job) return NextResponse.json({ error: 'Job not found' }, { status: 404 });
  return NextResponse.json({ job_id: jobId, ...job });
}
