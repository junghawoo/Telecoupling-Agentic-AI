import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, User } from 'lucide-react';
import { ToolCallCard } from './ToolCallCard';
import type { ChatMessage } from '../types';

interface Props {
  message: ChatMessage;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs
        ${isUser ? 'bg-violet-600 text-white' : 'bg-slate-700 text-slate-300'}`}>
        {isUser ? <User size={14} /> : <Bot size={14} />}
      </div>

      <div className={`flex flex-col gap-2 max-w-[85%] ${isUser ? 'items-end' : 'items-start'}`}>
        {/* Content bubble */}
        <div className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed
          ${isUser
            ? 'bg-violet-600 text-white rounded-tr-sm'
            : 'bg-slate-800 text-slate-200 rounded-tl-sm border border-slate-700'
          }`}>
          {isUser ? (
            <span className="whitespace-pre-wrap">{message.content}</span>
          ) : (
            <div className="prose prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
          {message.isStreaming && (
            <span className="inline-block w-1.5 h-4 bg-violet-400 animate-pulse ml-0.5 align-text-bottom" />
          )}
        </div>

        {/* Tool calls (collapsed by default) */}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="w-full space-y-1.5">
            <div className="text-xs text-slate-500 ml-1">
              {message.toolCalls.length} tool call{message.toolCalls.length > 1 ? 's' : ''}
            </div>
            {message.toolCalls.map((tc, i) => (
              <ToolCallCard key={i} record={tc} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
