import { useEffect, useState } from 'react';
import { useAnalysisStore } from '../../store/analysisStore';
import { buildCoachEvidence } from '../../services/coachEvidence';
import FeedbackTimeline from './FeedbackTimeline';

interface SavedAttempt {
  id: string;
  videoName: string;
  savedAt: string;
  metrics: { airTime: number | null; rotations: number | null; maxHeight: number | null };
}

export default function CoachSync() {
  const { userMetrics, referenceMetrics, userVideo, userAnalysis, isAnalyzing,
    userAngles, referenceAngles, manualMarkers, setCurrentTime, setIsPlaying, userVideoPadding } = useAnalysisStore();
  const [status, setStatus] = useState('');
  const [attempts, setAttempts] = useState<SavedAttempt[]>([]);
  const [question, setQuestion] = useState('');
  const [reply, setReply] = useState('');
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState('');
  const evidence = buildCoachEvidence(userAngles, referenceAngles, manualMarkers);

  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const controller = new AbortController();
    fetch('/api/coach/analysis', { signal: controller.signal })
      .then(response => response.ok ? response.json() : null)
      .then(data => { if (data && !controller.signal.aborted) setAttempts(data.attempts || []); })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  async function ask(prompt: string) {
    if (!prompt.trim() || asking) return;
    setAsking(true);
    setError('');
    try {
      const response = await fetch('/api/coach/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: prompt }),
      });
      if (!response.ok) throw new Error('Coach unavailable. Check npm run photon and try again.');
      const data = await response.json();
      setReply(data.reply);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not reach coach.');
    } finally { setAsking(false); }
  }

  useEffect(() => {
    if (!import.meta.env.DEV || isAnalyzing || !userAnalysis?.isComplete || !userMetrics || !userVideo) {
      setStatus('');
      return;
    }
    const controller = new AbortController();
    let retry: ReturnType<typeof setTimeout>;
    setReply('');
    async function sync() {
      setStatus('Sharing latest results with your text coach…');
      try {
        const response = await fetch('/api/coach/analysis', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            videoName: userVideo!.name,
            metrics: userMetrics,
            referenceMetrics,
            evidence: buildCoachEvidence(userAngles, referenceAngles, manualMarkers),
          }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error('Sync failed');
        const data = await response.json();
        if (!controller.signal.aborted) {
          setStatus('Results ready for your text coach. Ask about your latest attempt.');
          setAttempts(data.attempts || []);
        }
      } catch {
        if (controller.signal.aborted) return;
        setStatus('Coach offline. Start npm run photon; results will sync automatically.');
        retry = setTimeout(sync, 5000);
      }
    }
    void sync();
    return () => { controller.abort(); clearTimeout(retry); };
  }, [userMetrics, referenceMetrics, userVideo, userAnalysis?.isComplete, isAnalyzing, userAngles, referenceAngles, manualMarkers]);

  if (!import.meta.env.DEV) return null;
  return (
    <section className="bg-gray-900 border border-gray-700 rounded-2xl p-4 mb-4 space-y-3">
      <h2 className="text-white font-semibold">Your figure skating coach</h2>
      <p role="status" className="text-xs text-gray-400">{status || 'Analyze a jump to share measured results with your coach.'}</p>
      <p className="text-xs text-gray-400">Your questions and saved measurements are sent to OpenAI. Video stays local.</p>
      <button type="button" disabled={asking || !attempts.length}
        onClick={() => void ask('Review my latest attempt. Give up to three areas to review using measured differences and timestamps, then suggest a practice goal for coach approval.')}
        className="bg-blue-600 rounded-lg px-3 py-2 text-sm text-white disabled:opacity-40">
        {asking ? 'Reviewing…' : 'Review my latest jump'}
      </button>
      <form className="flex gap-2" onSubmit={event => { event.preventDefault(); void ask(question); }}>
        <input aria-label="Ask your figure skating coach" maxLength={2000} value={question}
          onChange={event => setQuestion(event.target.value)} placeholder="What changed between my last two jumps?"
          className="min-w-0 flex-1 bg-gray-800 rounded-lg px-3 py-2 text-sm text-white" />
        <button disabled={asking || !question.trim()} className="text-blue-300 text-sm disabled:opacity-40">Ask</button>
      </form>
      {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
      {reply && <p className="whitespace-pre-wrap text-sm text-gray-200" aria-live="polite">{reply}</p>}
      {evidence.length > 0 && <div className="space-y-2">
        <h3 className="text-sm text-white">Measured frames · tap to review</h3>
        {evidence.map(item => <button key={`${item.phase}-${item.joint}`} type="button"
          onClick={() => {
            setIsPlaying(false);
            for (const [type, time] of [['user', item.timestamp], ['reference', item.referenceTimestamp]] as const) {
              const video = document.querySelector<HTMLVideoElement>(`video[data-video-type="${type}"]`);
              if (video && Number.isFinite(video.duration)) {
                video.pause();
                video.currentTime = Math.min(time, video.duration);
              }
            }
            setCurrentTime(item.timestamp + userVideoPadding);
          }}
          className="block text-left text-xs text-blue-200 hover:underline">
          {item.timestamp.toFixed(2)}s · {item.phase} · {item.joint.replace(/([A-Z])/g, ' $1').toLowerCase()}: {item.angle}° vs {item.referenceAngle}° reference ({item.difference > 0 ? '+' : ''}{item.difference}°)
        </button>)}
        <p className="text-xs text-gray-500">Pose estimates near manually marked phases. Differences are observations, not a technique score.</p>
      </div>}
      <FeedbackTimeline refreshKey={status} />
    </section>
  );
}
