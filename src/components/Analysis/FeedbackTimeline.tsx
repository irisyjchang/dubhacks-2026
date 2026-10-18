import { useEffect, useState } from 'react';

interface FeedbackEntry {
  id: string;
  videoName: string;
  savedAt: string;
  feedback: { headline: string | null; report?: string; provenance: { generator: string | null; status: string | null } };
}

function TimelineEntry({ entry }: { entry: FeedbackEntry }) {
  const [report, setReport] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  async function read() {
    if (report || loading) return;
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`/api/coach/timeline/${entry.id}`);
      if (!response.ok) throw new Error('Could not load feedback. Close and reopen to retry.');
      const data: FeedbackEntry = await response.json();
      setReport(data.feedback.report || '');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not load feedback.'); }
    finally { setLoading(false); }
  }
  return <li className="border-l-2 border-blue-500 pl-3 py-2 space-y-2">
    <time dateTime={entry.savedAt} className="text-xs text-gray-400">{new Date(entry.savedAt).toLocaleString()}</time>
    <h4 className="text-sm text-white break-words">{entry.videoName}</h4>
    <p className="text-sm text-gray-300">{entry.feedback.headline || 'Saved coaching feedback'}</p>
    <p className="text-xs text-gray-400">{entry.feedback.provenance.generator}{entry.feedback.provenance.status === 'partial' ? ' · Partial report' : ''}</p>
    <details onToggle={event => { if (event.currentTarget.open) void read(); }}>
      <summary className="cursor-pointer text-sm text-blue-300">Read full feedback</summary>
      {loading && <p role="status" className="text-sm text-gray-400">Loading…</p>}
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {report && <pre className="whitespace-pre-wrap text-sm text-gray-200 max-h-96 overflow-auto mt-3 font-sans">{report}</pre>}
    </details>
  </li>;
}

export default function FeedbackTimeline({ refreshKey }: { refreshKey: string }) {
  const [entries, setEntries] = useState<FeedbackEntry[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetch('/api/coach/timeline', { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error('Feedback history is unavailable.');
        const data = await response.json();
        if (!controller.signal.aborted) { setEntries(data.items); setCursor(data.nextCursor); setError(''); }
      }).catch(cause => { if (!controller.signal.aborted) setError(cause.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refreshKey]);
  async function load(reset: boolean) {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`/api/coach/timeline${!reset && cursor ? `?before=${encodeURIComponent(cursor)}` : ''}`);
      if (!response.ok) throw new Error('Could not load feedback history.');
      const data = await response.json();
      setEntries(previous => reset ? data.items : [...previous, ...data.items]);
      setCursor(data.nextCursor);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not load feedback history.'); }
    finally { setLoading(false); }
  }
  return <section className="border-t border-gray-700 pt-3 space-y-3" aria-label="Your feedback timeline">
    <div className="flex justify-between items-center gap-3">
      <h3 className="text-white text-sm font-semibold">Your feedback timeline</h3>
      <button type="button" disabled={loading} onClick={() => void load(true)} className="text-blue-300 text-xs disabled:opacity-40">Refresh</button>
    </div>
    {loading && <p role="status" className="text-xs text-gray-400">Loading feedback…</p>}
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
    {!loading && !error && !entries.length && <p className="text-xs text-gray-400">Your saved feedback will appear here after analysis.</p>}
    <ol className="space-y-3">{entries.map(entry => <TimelineEntry key={entry.id} entry={entry} />)}</ol>
    {cursor && <button type="button" disabled={loading} onClick={() => void load(false)} className="text-blue-300 text-sm disabled:opacity-40">Load earlier feedback</button>}
  </section>;
}
