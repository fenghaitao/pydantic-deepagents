// Shared in-process job store — module is cached by Next.js, so the Map persists
export interface Job { status: 'running' | 'done' | 'error'; message: string }
const jobs = new Map<string, Job>();
export const setJob = (id: string, job: Job) => jobs.set(id, job);
export const getJob = (id: string) => jobs.get(id);
