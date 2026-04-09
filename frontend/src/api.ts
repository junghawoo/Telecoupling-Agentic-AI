import type { AgentStreamEvent, MCPTool, JobSummary, UploadedFile } from './types';

const BASE = '';  // proxied via vite dev server

export async function fetchTools(): Promise<MCPTool[]> {
  const r = await fetch(`${BASE}/agent/tools`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const data = await r.json();
  return data.tools ?? [];
}

export async function fetchJobs(): Promise<JobSummary[]> {
  const r = await fetch(`${BASE}/jobs`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const data = await r.json();
  return data.jobs ?? [];
}

export async function fetchHealth() {
  const r = await fetch(`${BASE}/health`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function uploadFile(file: File): Promise<UploadedFile> {
  const form = new FormData();
  form.append('file', file);
  const r = await fetch(`${BASE}/files/upload`, { method: 'POST', body: form });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`Upload failed (HTTP ${r.status}): ${text}`);
  }
  return r.json();
}

export async function deleteUploadedFile(filename: string): Promise<void> {
  const r = await fetch(`${BASE}/files/${encodeURIComponent(filename)}`, { method: 'DELETE' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}

/**
 * Streams agent events via SSE-like newline-delimited JSON.
 * Calls onEvent for each parsed AgentStreamEvent.
 * Returns when the stream closes.
 */
export async function streamChat(
  messages: { role: string; content: string }[],
  onEvent: (event: AgentStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await fetch(`${BASE}/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
    signal,
  });

  if (!r.ok) {
    const text = await r.text();
    throw new Error(`HTTP ${r.status}: ${text}`);
  }

  const reader = r.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() ?? '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith(':')) continue;
      // SSE: "data: {...}"
      const payload = trimmed.startsWith('data: ') ? trimmed.slice(6) : trimmed;
      try {
        const event = JSON.parse(payload) as AgentStreamEvent;
        onEvent(event);
      } catch {
        // ignore malformed lines
      }
    }
  }
  // flush remainder
  if (buf.trim()) {
    const payload = buf.trim().startsWith('data: ') ? buf.trim().slice(6) : buf.trim();
    try {
      onEvent(JSON.parse(payload) as AgentStreamEvent);
    } catch { /* ignore */ }
  }
}
