import { ChatPanel } from './components/ChatPanel';
import { Sidebar } from './components/Sidebar';
import { Globe } from 'lucide-react';

export default function App() {
  return (
    <div className="flex h-screen bg-slate-900 overflow-hidden">
      {/* Sidebar */}
      <div className="w-64 shrink-0 border-r border-slate-700 bg-slate-900 overflow-hidden flex flex-col">
        {/* Logo */}
        <div className="flex items-center gap-2.5 px-4 py-3.5 border-b border-slate-700">
          <Globe size={18} className="text-violet-400" />
          <span className="font-semibold text-slate-200 text-sm">Telecoupling AI</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          <Sidebar />
        </div>
      </div>

      {/* Main chat */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-hidden">
          <ChatPanel />
        </div>
      </div>
    </div>
  );
}
