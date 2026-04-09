import { useState, useEffect } from 'react';
import { Wrench, ChevronDown, ChevronRight, Layers, CheckCircle, Clock, AlertCircle } from 'lucide-react';
import { fetchTools, fetchJobs, fetchHealth } from '../api';
import type { MCPTool, JobSummary } from '../types';

export function Sidebar() {
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [toolsOpen, setToolsOpen] = useState(true);
  const [jobsOpen, setJobsOpen] = useState(true);

  useEffect(() => {
    fetchHealth().then(setHealth).catch(console.error);
    fetchTools().then(setTools).catch(console.error);
    fetchJobs().then(setJobs).catch(console.error);
  }, []);

  const statusIcon = (status: string) => {
    if (status === 'completed') return <CheckCircle size={12} className="text-emerald-400" />;
    if (status === 'failed') return <AlertCircle size={12} className="text-red-400" />;
    return <Clock size={12} className="text-amber-400" />;
  };

  return (
    <aside className="flex flex-col gap-4 h-full overflow-y-auto py-4 px-3">
      {/* System status */}
      {health && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3 space-y-1.5">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 uppercase tracking-wider">
            <Layers size={12} />
            System
          </div>
          <div className="flex items-center gap-1.5 text-xs">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
            <span className="text-slate-300">{String(health.active_model)}</span>
          </div>
          <div className="text-xs text-slate-500">
            {String(health.tool_count)} tools · {(health.mcp_servers as string[])?.join(', ')}
          </div>
        </div>
      )}

      {/* Tools */}
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 overflow-hidden">
        <button
          onClick={() => setToolsOpen(o => !o)}
          className="w-full flex items-center gap-2 px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider hover:bg-slate-700/40 transition-colors"
        >
          <Wrench size={12} />
          <span className="flex-1 text-left">MCP Tools ({tools.length})</span>
          {toolsOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>

        {toolsOpen && (
          <div className="border-t border-slate-700 divide-y divide-slate-700/50 max-h-64 overflow-y-auto">
            {tools.map(tool => (
              <div key={tool.name} className="px-3 py-1.5">
                <div className="font-mono text-xs text-violet-300">{tool.name}</div>
                <div className="text-xs text-slate-500 mt-0.5 truncate">{tool.description}</div>
              </div>
            ))}
            {tools.length === 0 && (
              <div className="px-3 py-2 text-xs text-slate-600">No tools loaded</div>
            )}
          </div>
        )}
      </div>

      {/* Jobs */}
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 overflow-hidden">
        <button
          onClick={() => setJobsOpen(o => !o)}
          className="w-full flex items-center gap-2 px-3 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider hover:bg-slate-700/40 transition-colors"
        >
          <Clock size={12} />
          <span className="flex-1 text-left">Recent Jobs ({jobs.length})</span>
          {jobsOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </button>

        {jobsOpen && (
          <div className="border-t border-slate-700 divide-y divide-slate-700/50 max-h-64 overflow-y-auto">
            {jobs.slice(0, 20).map(job => (
              <div key={job.job_id} className="px-3 py-1.5 flex items-start gap-2">
                <span className="mt-0.5 shrink-0">{statusIcon(job.status)}</span>
                <div className="min-w-0">
                  <div className="font-mono text-xs text-slate-400 truncate">{job.job_id}</div>
                  <div className="text-xs text-slate-600">
                    {job.tool_call_count} calls · {job.status}
                  </div>
                </div>
              </div>
            ))}
            {jobs.length === 0 && (
              <div className="px-3 py-2 text-xs text-slate-600">No jobs yet</div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
