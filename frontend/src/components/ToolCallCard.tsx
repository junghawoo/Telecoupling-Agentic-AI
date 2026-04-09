import { useState } from 'react';
import { ChevronDown, ChevronRight, CheckCircle, XCircle, Wrench } from 'lucide-react';
import type { ToolCallRecord } from '../types';

interface Props {
  record: ToolCallRecord;
}

export function ToolCallCard({ record }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/50 overflow-hidden text-sm">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-slate-700/50 transition-colors text-left"
      >
        <Wrench size={14} className="text-violet-400 shrink-0" />
        <span className="font-mono text-violet-300 flex-1">{record.tool}</span>
        <span className={`text-xs px-1.5 py-0.5 rounded ${record.success ? 'text-emerald-400' : 'text-red-400'}`}>
          {record.success ? <CheckCircle size={13} /> : <XCircle size={13} />}
        </span>
        <span className="text-slate-500 text-xs">{record.duration_ms}ms</span>
        {open ? <ChevronDown size={13} className="text-slate-500" /> : <ChevronRight size={13} className="text-slate-500" />}
      </button>

      {open && (
        <div className="border-t border-slate-700 px-3 py-2 space-y-2">
          <div>
            <div className="text-slate-500 text-xs mb-1">Arguments</div>
            <pre className="bg-slate-900 rounded p-2 text-xs text-slate-300 overflow-x-auto whitespace-pre-wrap break-all">
              {JSON.stringify(record.arguments, null, 2)}
            </pre>
          </div>
          <div>
            <div className="text-slate-500 text-xs mb-1">Result</div>
            <pre className="bg-slate-900 rounded p-2 text-xs text-slate-300 overflow-x-auto whitespace-pre-wrap break-all max-h-48">
              {record.result}
            </pre>
          </div>
          {record.error && (
            <div className="text-red-400 text-xs">{record.error}</div>
          )}
        </div>
      )}
    </div>
  );
}
