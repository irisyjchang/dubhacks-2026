"use client";
import Image from "next/image";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { WelcomeGreeting } from "@/components/auth/AuthControls";
import { useSessionMedia } from "@/components/media/SessionMedia";
import { useAnalysis } from "@/components/api/AnalysisProvider";
import { useAnalysisRoute } from "@/lib/use-analysis-route";
import { skateApi } from "@/lib/api";
import type { HistoryVideo } from "@/types/api";
import { useExperience } from "./ExperienceShell";
import { Icon } from "./Icons";

export function HomeScreen({ authEnabled }: { authEnabled: boolean }) {
  useAnalysisRoute();
  const { media } = useSessionMedia();
  const { chooseFootage } = useExperience();
  if (media.src) return null;
  return (
    <section className="welcome-scene">
      <p className="eyebrow">A little closer to your best.</p>
      <h1>
        <WelcomeGreeting enabled={authEnabled} />
      </h1>
      <button type="button" className="add-footage" onClick={chooseFootage}>
        <Icon name="add" />
        <span>Add Footage</span>
      </button>
      <p className="welcome-note">Your movement. A new perspective.</p>
    </section>
  );
}
export function AnalysisScreen() {
  useAnalysisRoute();
  const { media } = useSessionMedia();
  const { chooseFootage, openFeedback } = useExperience();
  const { analysis, status } = useAnalysis();
  if (!media.src)
    return (
      <section className="welcome-scene">
        <p className="eyebrow">See the smallest details.</p>
        <h1>It starts with your footage.</h1>
        <button type="button" className="add-footage" onClick={chooseFootage}>
          <Icon name="add" />
          <span>Add Footage</span>
        </button>
      </section>
    );
  return (
    <div className="analysis-caption">
      <h1>In motion.</h1>
      {analysis && (
        <button
          type="button"
          onClick={openFeedback}
          className="score-preview"
          aria-label="View analysis feedback"
        >
          <span>
            {analysis.score.toFixed(1)}
            <small>/10</small>
          </span>
          <span>
            {analysis.moves.length}{" "}
            {analysis.moves.length === 1 ? "element" : "elements"} observed{" "}
            <span aria-hidden="true">↗</span>
          </span>
        </button>
      )}
      {status === "ready" && !analysis && (
        <p className="quiet">Your footage is ready.</p>
      )}
    </div>
  );
}
export function LibraryScreen() {
  const router = useRouter();
  const { media } = useSessionMedia();
  const { openAnalysis, analysisId, status } = useAnalysis();
  const { chooseFootage } = useExperience();
  const [videos, setVideos] = useState<HistoryVideo[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const task = new AbortController();
    let busy = false;
    const refresh = async () => {
      if (busy) return;
      busy = true;
      try {
        const result = await skateApi.history(task.signal);
        if (!task.signal.aborted) {
          setVideos(
            result.videos.toSorted((a, b) => b.uploaded_at - a.uploaded_at),
          );
          setError("");
        }
      } catch (cause) {
        if (!task.signal.aborted)
          setError(
            cause instanceof Error ? cause.message : "Could not load footage.",
          );
      } finally {
        busy = false;
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => {
      clearInterval(timer);
      task.abort();
    };
  }, [attempt, analysisId, status]);
  return (
    <section className="library-scene">
      <div className="library-heading">
        <div>
          <p className="eyebrow">Time, collected.</p>
          <h1>Your footage.</h1>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="Add Footage"
          title="Add Footage"
          onClick={chooseFootage}
        >
          <Icon name="add" />
        </button>
      </div>
      {error && (
        <p role="alert" className="library-message">
          {error}{" "}
          <button
            type="button"
            className="text-action"
            onClick={() => setAttempt((n) => n + 1)}
          >
            Try again
          </button>
        </p>
      )}
      {!videos && !error && (
        <p className="library-message" role="status">
          Gathering your footage…
        </p>
      )}
      {videos?.length === 0 && (
        <p className="library-message">
          Your next moment belongs here. Add footage to begin.
        </p>
      )}
      <div className="footage-archive">
        {videos?.map((video, index) => (
          <button
            type="button"
            className="archive-clip"
            key={video.analysis_id}
            aria-label={`Open ${video.filename || `Footage ${index + 1}`}`}
            aria-pressed={media.analysisId === video.analysis_id}
            disabled={video.status === "failed" && !video.video_url}
            onClick={() => {
              openAnalysis(video.analysis_id, video);
              router.push("/");
            }}
          >
            <div className="archive-image">
              {video.thumbnail_url ? (
                <Image
                  unoptimized
                  width={220}
                  height={164}
                  src={video.thumbnail_url}
                  alt=""
                  loading="lazy"
                  onError={(event) => {
                    event.currentTarget.style.visibility = "hidden";
                  }}
                />
              ) : (
                <span className="archive-placeholder">
                  <Icon name="play" />
                </span>
              )}
              <span className="clip-duration">
                {video.duration_s != null
                  ? `${Math.floor(video.duration_s / 60)}:${String(Math.floor(video.duration_s % 60)).padStart(2, "0")}`
                  : video.status === "processing"
                    ? "Processing"
                    : video.status === "failed"
                      ? "Analysis failed"
                      : "Footage"}
              </span>
              {media.analysisId === video.analysis_id && (
                <span className="active-clip-label">Now playing</span>
              )}
            </div>
            <span className="clip-name">
              {video.filename?.replace(/\.[^.]+$/, "") ||
                `Footage ${index + 1}`}
            </span>
            <span className="clip-meta">
              {new Date(video.uploaded_at * 1000).toLocaleDateString(
                undefined,
                { month: "short", day: "numeric" },
              )}
              {video.score != null ? ` · ${video.score.toFixed(1)}/10` : ""}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
