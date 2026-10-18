"use client";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useSessionMedia } from "@/components/media/SessionMedia";
import { useAnalysis } from "@/components/api/AnalysisProvider";
import { PoseCanvas } from "@/components/analysis/PoseCanvas";

export function PersistentStage({
  pose,
  geometry,
}: {
  pose: boolean;
  geometry: boolean;
}) {
  const {
    media,
    videoRef,
    pendingPlaybackRef,
    presentation,
    playback,
    updateLook,
    updatePlayback,
  } = useSessionMedia();
  const { analysis } = useAnalysis();
  const src = presentation?.src || media.src;
  const sampledSource = useRef("");
  const [aspect, setAspect] = useState(16 / 9);
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !src) return;
    const canvas = document.createElement("canvas");
    canvas.width = 32;
    canvas.height = 24;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    const sample = () => {
      if (!context || video.readyState < 2 || !video.videoWidth) return;
      try {
        context.drawImage(video, 0, 0, 32, 24);
        const { data } = context.getImageData(0, 0, 32, 24);
        let r = 0,
          g = 0,
          b = 0,
          count = 0;
        // Sample the actual scene, leaving out its brightest ice and darkest letterboxing.
        for (let i = 0; i < data.length; i += 4) {
          const light = (data[i] + data[i + 1] + data[i + 2]) / 3;
          if (light < 18 || light > 235) continue;
          r += data[i];
          g += data[i + 1];
          b += data[i + 2];
          count++;
        }
        if (!count) return;
        const tint = {
          r: Math.round(r / count),
          g: Math.round(g / count),
          b: Math.round(b / count),
        };
        const first = sampledSource.current !== src;
        sampledSource.current = src;
        updateLook({
          tint,
          accent: `rgb(${tint.r}, ${tint.g}, ${tint.b})`,
          ...(first ? { poster: canvas.toDataURL("image/jpeg", 0.65) } : {}),
        });
      } catch {
        /* Media without CORS still plays; its poster supplies the atmosphere. */
      }
    };
    video.addEventListener("loadeddata", sample);
    video.addEventListener("seeked", sample);
    const timer = window.setInterval(() => {
      if (!video.paused) sample();
    }, 1500);
    sample();
    return () => {
      clearInterval(timer);
      video.removeEventListener("loadeddata", sample);
      video.removeEventListener("seeked", sample);
    };
  }, [src, videoRef, updateLook]);

  const showPose = Boolean(
    analysis?.pose &&
      analysis.analysis_id === media.analysisId &&
      !presentation &&
      (pose || geometry),
  );
  return (
    <div className="video-stage" aria-label="Active footage">
      <div className="scene-wash" />
      {media.poster && (
        <div
          className="scene-memory"
          style={{ backgroundImage: `url("${media.poster}")` }}
        />
      )}
      <video
        data-testid="footage-player"
        ref={videoRef}
        className="footage-player"
        style={{ "--video-aspect": aspect } as CSSProperties}
        src={src || undefined}
        crossOrigin="anonymous"
        playsInline
        loop
        preload="auto"
        muted={playback.muted}
        onLoadedMetadata={(event) => {
          const video = event.currentTarget;
          setAspect(video.videoWidth / video.videoHeight || 16 / 9);
          video.playbackRate = playback.rate;
          const pending = pendingPlaybackRef.current;
          if (pending) {
            video.currentTime = Math.min(
              Math.max(0, video.duration - 0.01),
              pending.time,
            );
            pendingPlaybackRef.current = null;
            if (pending.play)
              void video.play().catch(() => updatePlayback({ playing: false }));
          }
          updatePlayback({
            duration: video.duration,
            ready: true,
            error: null,
          });
        }}
        onTimeUpdate={(event) =>
          updatePlayback({ time: event.currentTarget.currentTime })
        }
        onPlay={() => updatePlayback({ playing: true, error: null })}
        onPause={() => updatePlayback({ playing: false })}
        onError={() => {
          if (src)
            updatePlayback({
              ready: false,
              error:
                "This footage could not load. Try selecting it again or add the original video.",
            });
        }}
      />
      {showPose && (
        <PoseCanvas
          videoRef={videoRef}
          pose={analysis!.pose!}
          geometry={geometry}
          showSkeleton={pose}
        />
      )}
      <div className="scene-feather" />
    </div>
  );
}
