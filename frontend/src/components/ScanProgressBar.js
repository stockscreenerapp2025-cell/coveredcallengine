import { useEffect, useRef, useState } from 'react';
import { CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import { screenerApi } from '../lib/api';

const STAGES = [
  'Loading market snapshot',
  'Scanning symbols',
  'Scoring & filtering results',
  'Enriching data (IV Rank + Analyst)',
  'Running technical analysis',
  'Done',
];

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export default function ScanProgressBar({ active, onComplete }) {
  const [progress, setProgress] = useState(null);
  const intervalRef = useRef(null);
  const completedRef = useRef(false);

  useEffect(() => {
    if (!active) {
      // Reset when not active
      if (!completedRef.current) {
        setProgress(null);
      }
      return;
    }

    completedRef.current = false;

    const poll = async () => {
      try {
        const res = await screenerApi.getScanProgress();
        const data = res.data;
        setProgress(data);

        if (!data.active && data.pct === 100) {
          // Done — wait 3s then close
          completedRef.current = true;
          clearInterval(intervalRef.current);
          setTimeout(() => {
            setProgress(null);
            completedRef.current = false;
            if (onComplete) onComplete(data.opportunities_found);
          }, 3000);
        }

        if (!data.active && data.error) {
          clearInterval(intervalRef.current);
        }
      } catch {
        // Silently ignore poll errors
      }
    };

    poll();
    intervalRef.current = setInterval(poll, 1500);

    return () => clearInterval(intervalRef.current);
  }, [active]);

  if (!progress && !active) return null;
  if (!progress) return null;

  const isDone = !progress.active && progress.pct === 100 && !progress.error;
  const isError = !!progress.error;
  const pct = progress.pct || 0;

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 w-full max-w-lg px-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl p-4 space-y-3">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {isDone ? (
              <CheckCircle className="w-4 h-4 text-emerald-400" />
            ) : isError ? (
              <AlertCircle className="w-4 h-4 text-red-400" />
            ) : (
              <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />
            )}
            <span className={`text-sm font-medium ${
              isDone ? 'text-emerald-400' : isError ? 'text-red-400' : 'text-zinc-100'
            }`}>
              {isDone
                ? `Scan complete — ${progress.opportunities_found} opportunities found`
                : isError
                ? `Scan failed: ${progress.error}`
                : 'Scanning Market...'}
            </span>
          </div>
          {progress.elapsed_seconds > 0 && (
            <span className="text-xs text-zinc-500 font-mono">
              {formatTime(progress.elapsed_seconds)}
            </span>
          )}
        </div>

        {/* Progress bar */}
        <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              isDone ? 'bg-emerald-500' : isError ? 'bg-red-500' : 'bg-cyan-500'
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>

        {/* Stage + symbol details */}
        {!isDone && !isError && (
          <div className="flex items-center justify-between text-xs text-zinc-400">
            <span>{progress.stage}</span>
            <div className="flex items-center gap-3">
              {progress.current_symbol && (
                <span className="font-mono text-zinc-300">
                  {progress.current_symbol}
                  {progress.total_symbols > 0 && (
                    <span className="text-zinc-500">
                      {' '}({progress.symbols_done} / {progress.total_symbols})
                    </span>
                  )}
                </span>
              )}
              {progress.opportunities_found > 0 && (
                <span className="text-emerald-400">
                  {progress.opportunities_found} found
                </span>
              )}
            </div>
          </div>
        )}

        {/* Stage dots */}
        <div className="flex items-center gap-1.5">
          {STAGES.slice(0, 5).map((s, i) => (
            <div
              key={i}
              className={`h-1 flex-1 rounded-full transition-all duration-300 ${
                i < progress.stage_index
                  ? 'bg-emerald-500'
                  : i === progress.stage_index && !isDone
                  ? 'bg-cyan-400'
                  : 'bg-zinc-700'
              }`}
            />
          ))}
        </div>

      </div>
    </div>
  );
}
