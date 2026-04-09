export type Role = 'user' | 'assistant';

export interface UploadedFile {
  filename: string;
  path: string;
  size_bytes: number;
  extension: string;
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  toolCalls?: ToolCallRecord[];
  isStreaming?: boolean;
}

export interface ToolCallRecord {
  tool: string;
  arguments: Record<string, unknown>;
  result: string;
  success: boolean;
  error?: string | null;
  duration_ms: number;
}

export interface AgentStreamEvent {
  type: 'classified' | 'thinking' | 'tool_call' | 'tool_result' | 'response' | 'error';
  data: Record<string, unknown>;
}

export interface MCPTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export interface JobSummary {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  created_at: string;
  duration_ms?: number;
  tool_call_count: number;
  model: string;
}
