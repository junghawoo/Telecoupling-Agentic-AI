import { useState, useRef, useEffect, useCallback } from 'react';
import { Send, StopCircle, Paperclip, X, FileText } from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';
import { MessageBubble } from './MessageBubble';
import { ThinkingIndicator } from './ThinkingIndicator';
import { streamChat, uploadFile, deleteUploadedFile } from '../api';
import type { ChatMessage, ToolCallRecord, AgentStreamEvent, UploadedFile } from '../types';

const EXAMPLE_PROMPTS = [
  'List all available InVEST models',
  'Run a Habitat Quality model on the sample data',
  'What InVEST models are best for studying telecoupling between agriculture and biodiversity?',
  'Run Carbon Storage model and interpret the results in a telecoupling context',
];

const ACCEPTED_EXTENSIONS = '.tif,.tiff,.csv,.shp,.gpkg,.geojson,.json,.zip';

interface StreamState {
  iteration?: number;
  currentTool?: string;
  classifiedLabel?: string;
  isThinking: boolean;
}

export function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [streamState, setStreamState] = useState<StreamState>({ isThinking: false });
  const [attachments, setAttachments] = useState<UploadedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streaming]);

  // -------------------------------------------------------------------------
  // File upload
  // -------------------------------------------------------------------------

  const handleFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    e.target.value = '';   // reset so the same file can be re-selected

    setUploading(true);
    try {
      const uploaded = await Promise.all(files.map(f => uploadFile(f)));
      setAttachments(prev => [...prev, ...uploaded]);
    } catch (err) {
      console.error('Upload error', err);
      alert(`Upload failed: ${(err as Error).message}`);
    } finally {
      setUploading(false);
    }
  }, []);

  const removeAttachment = useCallback(async (file: UploadedFile) => {
    setAttachments(prev => prev.filter(f => f.filename !== file.filename));
    try {
      await deleteUploadedFile(file.filename);
    } catch {
      // best-effort delete; file may already be gone
    }
  }, []);

  // -------------------------------------------------------------------------
  // SSE event handler
  // -------------------------------------------------------------------------

  const handleEvent = useCallback((event: AgentStreamEvent, pendingTools: ToolCallRecord[]) => {
    switch (event.type) {
      case 'classified':
        setStreamState(s => ({ ...s, classifiedLabel: event.data.label as string }));
        break;

      case 'thinking':
        setStreamState(s => ({ ...s, isThinking: true, iteration: event.data.iteration as number }));
        break;

      case 'tool_call':
        setStreamState(s => ({ ...s, currentTool: event.data.tool as string }));
        break;

      case 'tool_result': {
        const record: ToolCallRecord = {
          tool: event.data.tool as string,
          arguments: (event.data.arguments as Record<string, unknown>) ?? {},
          result: (event.data.preview as string) ?? '',
          success: event.data.success as boolean,
          duration_ms: event.data.duration_ms as number,
        };
        pendingTools.push(record);
        setStreamState(s => ({ ...s, currentTool: undefined }));
        break;
      }

      case 'response': {
        const text = event.data.text as string;
        const toolCalls = event.data.tool_calls as ToolCallRecord[] | undefined;
        const finalTools = toolCalls && toolCalls.length > 0 ? toolCalls : [...pendingTools];
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last && last.role === 'assistant' && last.isStreaming) {
            last.content = text;
            last.toolCalls = finalTools;
            last.isStreaming = false;
          } else {
            updated.push({ id: uuidv4(), role: 'assistant', content: text, toolCalls: finalTools });
          }
          return updated;
        });
        setStreamState({ isThinking: false });
        break;
      }

      case 'error': {
        const errMsg = event.data.message as string;
        setMessages(prev => [
          ...prev,
          { id: uuidv4(), role: 'assistant', content: `**Error:** ${errMsg}` },
        ]);
        setStreamState({ isThinking: false });
        break;
      }
    }
  }, []);

  // -------------------------------------------------------------------------
  // Send message
  // -------------------------------------------------------------------------

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || streaming) return;

    // Append uploaded file paths to the message so the LLM can reference them
    let content = text.trim();
    if (attachments.length > 0) {
      const pathList = attachments.map(f => `- ${f.path}`).join('\n');
      content += `\n\n**Uploaded files available at these paths:**\n${pathList}`;
    }

    const userMsg: ChatMessage = { id: uuidv4(), role: 'user', content };
    const assistantPlaceholder: ChatMessage = {
      id: uuidv4(), role: 'assistant', content: '', isStreaming: true,
    };

    setMessages(prev => [...prev, userMsg, assistantPlaceholder]);
    setInput('');
    setAttachments([]);
    setStreaming(true);
    setStreamState({ isThinking: true });

    // Send only the current user message — llama4 struggles with long histories
    // and hallucinates responses based on prior context instead of the new query.
    const history = [userMsg].map(m => ({
      role: m.role === 'assistant' ? 'model' : 'user',
      content: m.content,
    }));

    const pendingTools: ToolCallRecord[] = [];
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await streamChat(history, (event) => handleEvent(event, pendingTools), ctrl.signal);
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setMessages(prev => [
          ...prev,
          { id: uuidv4(), role: 'assistant', content: `**Network error:** ${(err as Error).message}` },
        ]);
      }
    } finally {
      setStreaming(false);
      setStreamState({ isThinking: false });
      abortRef.current = null;
    }
  }, [messages, streaming, attachments, handleEvent]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setStreaming(false);
    setStreamState({ isThinking: false });
    setMessages(prev => {
      const updated = [...prev];
      const last = updated[updated.length - 1];
      if (last?.isStreaming) last.isStreaming = false;
      return updated;
    });
  };

  const formatBytes = (n: number) =>
    n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-6 text-center">
            <div>
              <h2 className="text-2xl font-semibold text-slate-200 mb-1">Telecoupling AI</h2>
              <p className="text-slate-500 text-sm max-w-md">
                Agentic environmental analyst powered by InVEST + QGIS tools via MCP.
                Ask me to run models, analyse results, or plan geospatial workflows.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-xl">
              {EXAMPLE_PROMPTS.map(p => (
                <button
                  key={p}
                  onClick={() => sendMessage(p)}
                  className="text-left text-xs text-slate-400 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg px-3 py-2.5 transition-colors"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(msg => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {streamState.isThinking && (
          <ThinkingIndicator
            iteration={streamState.iteration}
            currentTool={streamState.currentTool}
            classifiedLabel={streamState.classifiedLabel}
          />
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-slate-700 px-4 py-3 space-y-2">

        {/* Attached file pills */}
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {attachments.map(f => (
              <span
                key={f.filename}
                className="inline-flex items-center gap-1.5 text-xs bg-slate-700 border border-slate-600 text-slate-300 rounded-md px-2 py-1"
              >
                <FileText size={11} className="text-violet-400 shrink-0" />
                <span className="max-w-[160px] truncate">{f.filename}</span>
                <span className="text-slate-500">{formatBytes(f.size_bytes)}</span>
                <button
                  onClick={() => removeAttachment(f)}
                  className="text-slate-500 hover:text-red-400 transition-colors"
                  title="Remove"
                >
                  <X size={11} />
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="flex gap-2 items-end bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 focus-within:border-violet-500 transition-colors">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_EXTENSIONS}
            className="hidden"
            onChange={handleFileChange}
          />

          {/* Attach button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={streaming || uploading}
            className="shrink-0 p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            title="Attach file (.tif, .csv, .shp, .gpkg, .geojson)"
          >
            <Paperclip size={16} className={uploading ? 'animate-spin' : ''} />
          </button>

          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about InVEST models, run analyses, or plan geospatial workflows…"
            rows={1}
            className="flex-1 bg-transparent text-slate-200 text-sm placeholder-slate-600 resize-none outline-none max-h-32 leading-relaxed"
            style={{ height: 'auto' }}
            onInput={e => {
              const t = e.target as HTMLTextAreaElement;
              t.style.height = 'auto';
              t.style.height = `${t.scrollHeight}px`;
            }}
            disabled={streaming}
          />

          {streaming ? (
            <button
              onClick={stop}
              className="shrink-0 p-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-white transition-colors"
              title="Stop"
            >
              <StopCircle size={16} />
            </button>
          ) : (
            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() && attachments.length === 0}
              className="shrink-0 p-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-30 disabled:cursor-not-allowed text-white transition-colors"
              title="Send (Enter)"
            >
              <Send size={16} />
            </button>
          )}
        </div>

        <p className="text-xs text-slate-600 text-center">
          Enter to send · Shift+Enter for newline · Attach .tif, .csv, .shp, .gpkg, .geojson
        </p>
      </div>
    </div>
  );
}
