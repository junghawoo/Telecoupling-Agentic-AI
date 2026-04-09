import { Brain } from 'lucide-react';

interface Props {
  iteration?: number;
  currentTool?: string;
  classifiedLabel?: string;
}

const INTENT_COLORS: Record<string, string> = {
  'InVEST Analysis':      'text-emerald-400',
  'Geospatial Operation': 'text-sky-400',
  'Follow-up Question':   'text-amber-400',
};

export function ThinkingIndicator({ iteration, currentTool, classifiedLabel }: Props) {
  const labelColor = classifiedLabel ? (INTENT_COLORS[classifiedLabel] ?? 'text-slate-400') : '';

  return (
    <div className="flex flex-col gap-1 w-fit">
      {classifiedLabel && (
        <span className={`text-xs px-2 ${labelColor}`}>
          Routing: {classifiedLabel}
        </span>
      )}
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/60 border border-slate-700 text-sm text-slate-400">
        <Brain size={14} className="text-violet-400 animate-pulse" />
        <span>
          {currentTool
            ? `Calling ${currentTool}…`
            : iteration
            ? `Reasoning (step ${iteration})…`
            : 'Thinking…'}
        </span>
        <span className="flex gap-0.5">
          {[0, 1, 2].map(i => (
            <span
              key={i}
              className="inline-block w-1 h-1 rounded-full bg-violet-400 animate-bounce"
              style={{ animationDelay: `${i * 150}ms` }}
            />
          ))}
        </span>
      </div>
    </div>
  );
}
