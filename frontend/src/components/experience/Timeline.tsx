"use client";
import Image from "next/image";
import { useEffect, useState } from "react";
import { useSessionMedia } from "@/components/media/SessionMedia";
import { useAnalysis } from "@/components/api/AnalysisProvider";
import { extractVideoFrames, type VideoFrame } from "@/lib/video-frames";
import { Icon } from "./Icons";
export function timecode(time: number) {
  const ms = Math.floor(Math.max(0, time) * 1000);
  return `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
}
export function Timeline({ detailed }: { detailed: boolean }) {
  const {
    media,
    presentation,
    playback,
    seek,
    togglePlay,
    toggleMuted,
    videoRef,
  } = useSessionMedia();
  const { analysis } = useAnalysis();
  const [decoded, setDecoded] = useState<{ src: string; frames: VideoFrame[] }>(
    { src: "", frames: [] },
  );
  const src = presentation?.src || media.src;
  const fps = analysis?.pose?.fps || 30;
  useEffect(() => {
    if (!src) return;
    const task = new AbortController();
    void extractVideoFrames(src, task.signal)
      .then((frames) => {
        if (!task.signal.aborted) setDecoded({ src, frames });
      })
      .catch(() => {});
    return () => task.abort();
  }, [src]);
  const frames = decoded.src === src ? decoded.frames : [];
  return (
    <section
      className={`timeline ${detailed ? "timeline-detailed" : ""}`}
      aria-label="Playback controls"
      hidden={!src}
    >
      <div className="scrub-line">
        <time>{timecode(playback.time)}</time>
        <input
          aria-label="Video timeline"
          type="range"
          min="0"
          max={playback.duration || 0.01}
          step={1 / fps}
          value={Math.min(playback.time, playback.duration || 0)}
          onChange={(event) => seek(Number(event.target.value), true)}
        />
        <time>{timecode(playback.duration)}</time>
      </div>
      <div className="transport">
        <div className="transport-side">
          <span>
            {presentation?.label ||
              media.fileName?.replace(/\.[^.]+$/, "") ||
              "Your footage"}
          </span>
        </div>
        <div className="transport-main">
          <button
            type="button"
            className="icon-button"
            aria-label="Previous frame"
            title="Previous frame"
            disabled={!playback.ready}
            onClick={() => seek(playback.time - 1 / fps, true)}
          >
            <Icon name="prev" />
          </button>
          <button
            type="button"
            className="icon-button play-button"
            aria-label={playback.playing ? "Pause footage" : "Play footage"}
            disabled={!playback.ready}
            onClick={togglePlay}
          >
            <Icon name={playback.playing ? "pause" : "play"} />
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Next frame"
            title="Next frame"
            disabled={!playback.ready}
            onClick={() => seek(playback.time + 1 / fps, true)}
          >
            <Icon name="next" />
          </button>
        </div>
        <div className="transport-side transport-end">
          <button
            type="button"
            className="icon-button"
            aria-label={playback.muted ? "Unmute footage" : "Mute footage"}
            onClick={toggleMuted}
          >
            <Icon name={playback.muted ? "muted" : "sound"} />
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Full screen"
            onClick={() => {
              void videoRef.current?.requestFullscreen?.();
            }}
          >
            <Icon name="expand" />
          </button>
        </div>
      </div>
      <div className="frame-strip" hidden={!detailed} aria-label="Key frames">
        {frames.map((frame, index) => (
          <button
            type="button"
            key={frame.time}
            aria-label={`Freeze frame at ${timecode(frame.time)}`}
            aria-pressed={
              Math.abs(playback.time - frame.time) < playback.duration / 7 / 2
            }
            onClick={() => seek(Math.round(frame.time * fps) / fps, true)}
          >
            <Image
              unoptimized
              width={220}
              height={164}
              src={frame.image}
              alt={`Frame ${index + 1}`}
            />
            <span>{timecode(frame.time)}</span>
          </button>
        ))}
        {!frames.length && <p className="quiet">Preparing frame previews…</p>}
      </div>
    </section>
  );
}
