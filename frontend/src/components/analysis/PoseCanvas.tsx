"use client";
import { useEffect, useRef, useState, type RefObject } from "react";
import { angleAt, hasTrackedBody, poseFrameAt } from "@/lib/pose-geometry";
import type { Pose } from "@/types/api";

type Keypoints = [number, number, number][];
const EDGES = [[0, 1], [0, 2], [1, 3], [2, 4], [5, 6], [5, 7], [7, 9], [6, 8], [8, 10], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16]];

export function PoseCanvas({ videoRef, pose, source, fit = "contain", positionY = 0.5, geometry = false, showSkeleton = true }: {
  videoRef: RefObject<HTMLVideoElement | null>;
  pose?: Pose;
  source: string;
  fit?: "contain" | "cover";
  positionY?: number;
  geometry?: boolean;
  showSkeleton?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState("");
  const options = useRef({ fit, positionY, geometry, showSkeleton });
  useEffect(() => { options.current = { fit, positionY, geometry, showSkeleton }; }, [fit, positionY, geometry, showSkeleton]);

  useEffect(() => {
    const video = videoRef.current, canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!video || !canvas || !context) return;
    let frameId = 0, cancelled = false, worker: Worker | undefined;
    let ready = false, busy = false, failed = false, lastRequested = -1;
    let local: { time: number; kp: Keypoints } | undefined;
    const startDetector = () => {
      if (worker || failed) return;
      setStatus("Loading pose tracking…");
      worker = new Worker(new URL("../../lib/pose-worker.ts", import.meta.url), { type: "module" });
      worker.onmessage = ({ data }) => {
        if (data.type === "ready") ready = true;
        if (data.type === "frame") {
          busy = false;
          local = { time: data.time, kp: data.kp };
        }
        if (data.type === "error") {
          failed = true;
          busy = false;
          setStatus("Pose tracking could not load. Turn both tools off and on to retry.");
        }
      };
      worker.onerror = () => {
        failed = true;
        busy = false;
        setStatus("Pose tracking could not load. Turn both tools off and on to retry.");
      };
      worker.postMessage({ type: "init" });
    };
    const draw = () => {
      if (cancelled) return;
      const { fit, positionY, geometry, showSkeleton } = options.current;
      const width = video.clientWidth, height = video.clientHeight;
      const density = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(width * density) || canvas.height !== Math.round(height * density)) {
        canvas.width = Math.round(width * density);
        canvas.height = Math.round(height * density);
      }
      context.setTransform(density, 0, 0, density, 0, 0);
      context.clearRect(0, 0, width, height);
      if (video.readyState >= 2 && !video.seeking && video.videoWidth) {
        const time = video.currentTime;
        const frame = pose ? poseFrameAt(pose.frames, time, pose.fps) : undefined;
        let threshold = pose?.min_confidence ?? 0.1;
        let kp = frame?.kp || [];
        let sourceWidth = pose?.width || video.videoWidth;
        let sourceHeight = pose?.height || video.videoHeight;
        if (!hasTrackedBody(kp, threshold)) {
          startDetector();
          // Detect the actual displayed frame, including paused frames and backwards seeks.
          if (ready && !busy && !failed && Math.abs(time - lastRequested) > 1 / 60) {
            busy = true;
            lastRequested = time;
            const resizeWidth = Math.min(640, video.videoWidth);
            void createImageBitmap(video, { resizeWidth, resizeHeight: Math.round(resizeWidth * video.videoHeight / video.videoWidth) }).then(bitmap => {
              if (cancelled) { bitmap.close(); return; }
              worker?.postMessage({ type: "detect", time, bitmap }, [bitmap]);
            }).catch(() => {
              busy = false;
              failed = true;
              setStatus("Pose tracking could not read this video frame.");
            });
          }
          kp = local && Math.abs(local.time - time) < (video.paused ? 1 / 120 : 0.15) ? local.kp : [];
          threshold = 0.35;
          sourceWidth = video.videoWidth;
          sourceHeight = video.videoHeight;
          if (ready && !failed) setStatus(hasTrackedBody(kp, threshold) ? "" : busy ? "Tracking pose…" : "No pose detected in this frame");
        } else setStatus("");
        if (kp.length) {
          const scale = (fit === "cover" ? Math.max : Math.min)(width / sourceWidth, height / sourceHeight);
          const drawWidth = sourceWidth * scale, drawHeight = sourceHeight * scale;
          const x = (width - drawWidth) / 2, y = (height - drawHeight) * positionY;
          const valid = (p: Keypoints[number] | undefined): p is Keypoints[number] => Boolean(p && p.every(Number.isFinite) && p[2] >= threshold);
          const point = (p: Keypoints[number]) => [x + p[0] * drawWidth, y + p[1] * drawHeight] as const;
          context.lineWidth = 2.5;
          context.lineCap = "round";
          context.shadowColor = "#00131f";
          context.shadowBlur = 4;
          context.strokeStyle = "#67e8f9";
          context.fillStyle = "#a5f3fc";
          if (showSkeleton) {
            for (const [a, b] of pose?.edges || EDGES) {
              const p = kp[a], q = kp[b];
              if (!valid(p) || !valid(q)) continue;
              context.beginPath(); context.moveTo(...point(p)); context.lineTo(...point(q)); context.stroke();
            }
            for (const p of kp) {
              if (!valid(p)) continue;
              context.beginPath(); context.arc(...point(p), 3, 0, Math.PI * 2); context.fill();
            }
          }
          if (geometry) {
            context.font = "600 13px sans-serif";
            context.strokeStyle = "#fff7dc";
            for (const [a, b, c] of [[5, 7, 9], [6, 8, 10], [11, 13, 15], [12, 14, 16]]) {
              const p = kp[a], q = kp[b], r = kp[c];
              if (!valid(p) || !valid(q) || !valid(r)) continue;
              const angle = angleAt([p[0] * sourceWidth, p[1] * sourceHeight], [q[0] * sourceWidth, q[1] * sourceHeight], [r[0] * sourceWidth, r[1] * sourceHeight]);
              if (angle == null) continue;
              context.beginPath(); context.moveTo(...point(p)); context.lineTo(...point(q)); context.lineTo(...point(r)); context.stroke();
              const label = `${Math.round(angle)}°`, [qx, qy] = point(q);
              const labelWidth = context.measureText(label).width;
              const labelX = Math.max(4, Math.min(width - labelWidth - 12, qx + (b === 7 || b === 13 ? -48 : 12)));
              const labelY = Math.max(22, Math.min(height - 8, qy - 10));
              context.fillStyle = "#071c2be6";
              context.fillRect(labelX - 4, labelY - 15, labelWidth + 8, 21);
              context.fillStyle = "#fff7dc";
              context.fillText(label, labelX, labelY);
            }
          }
        }
      }
      frameId = requestAnimationFrame(draw);
    };
    draw();
    return () => { cancelled = true; cancelAnimationFrame(frameId); worker?.terminate(); };
  }, [pose, source, videoRef]);
  return <>
    <canvas ref={canvasRef} data-testid="pose-overlay" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden />
    {status && <div role="status" className="pose-status">{status}</div>}
  </>;
}
