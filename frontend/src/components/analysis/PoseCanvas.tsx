"use client";
import { useEffect, useRef, type RefObject } from "react";
import { angleAt } from "@/lib/pose-geometry";
import type { Pose } from "@/types/api";

export function PoseCanvas({
  videoRef,
  pose,
  fit = "contain",
  positionY = 0.5,
  geometry = false,
  showSkeleton = true,
}: {
  videoRef: RefObject<HTMLVideoElement | null>;
  pose: Pose;
  fit?: "contain" | "cover";
  positionY?: number;
  geometry?: boolean;
  showSkeleton?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !pose) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    let frameId = 0;
    const draw = () => {
      const width = video.clientWidth,
        height = video.clientHeight;
      const density = window.devicePixelRatio || 1;
      if (
        canvas.width !== Math.round(width * density) ||
        canvas.height !== Math.round(height * density)
      ) {
        canvas.width = Math.round(width * density);
        canvas.height = Math.round(height * density);
      }
      context.setTransform(density, 0, 0, density, 0, 0);
      context.clearRect(0, 0, width, height);
      const frame =
        pose.frames[
          Math.min(
            pose.frames.length - 1,
            Math.round(video.currentTime * pose.fps),
          )
        ];
      if (frame) {
        // The player uses object-contain: offset the skeleton for letterboxing.
        const scale = (fit === "cover" ? Math.max : Math.min)(
          width / pose.width,
          height / pose.height,
        );
        const drawWidth = pose.width * scale,
          drawHeight = pose.height * scale;
        const x = (width - drawWidth) / 2,
          y = (height - drawHeight) * positionY;
        context.strokeStyle = "#67e8f9";
        context.fillStyle = "#a5f3fc";
        context.lineWidth = 2;
        const threshold = pose.min_confidence ?? 0.1;
        for (const [a, b] of showSkeleton ? pose.edges : []) {
          const p = frame.kp[a],
            q = frame.kp[b];
          if (!p || !q || p[2] < threshold || q[2] < threshold) continue;
          context.beginPath();
          context.moveTo(x + p[0] * drawWidth, y + p[1] * drawHeight);
          context.lineTo(x + q[0] * drawWidth, y + q[1] * drawHeight);
          context.stroke();
        }
        for (const p of showSkeleton ? frame.kp : []) {
          if (p[2] < threshold) continue;
          context.beginPath();
          context.arc(
            x + p[0] * drawWidth,
            y + p[1] * drawHeight,
            2.5,
            0,
            Math.PI * 2,
          );
          context.fill();
        }
        if (geometry) {
          context.font = "11px sans-serif";
          context.fillStyle = "#fff7dc";
          context.strokeStyle = "#fff7dc99";
          for (const [a, b, c] of [
            [5, 7, 9],
            [6, 8, 10],
            [11, 13, 15],
            [12, 14, 16],
          ]) {
            const p = frame.kp[a],
              q = frame.kp[b],
              r = frame.kp[c];
            if (!p || !q || !r || Math.min(p[2], q[2], r[2]) < threshold)
              continue;
            const angle = angleAt(
              [p[0] * pose.width, p[1] * pose.height],
              [q[0] * pose.width, q[1] * pose.height],
              [r[0] * pose.width, r[1] * pose.height],
            );
            if (angle == null) continue;
            context.beginPath();
            context.moveTo(x + p[0] * drawWidth, y + p[1] * drawHeight);
            context.lineTo(x + q[0] * drawWidth, y + q[1] * drawHeight);
            context.lineTo(x + r[0] * drawWidth, y + r[1] * drawHeight);
            context.stroke();
            context.fillText(
              `${Math.round(angle)}°`,
              x + q[0] * drawWidth + (b === 7 || b === 13 ? -36 : 10),
              y + q[1] * drawHeight - 8,
            );
          }
        }
        const boxes = showSkeleton ? pose.skater_boxes || [] : [];
        if (boxes.length) {
          let near = boxes[0];
          for (const box of boxes) {
            if (
              Math.abs(box.t - video.currentTime) <
              Math.abs(near.t - video.currentTime)
            )
              near = box;
          }
          context.strokeRect(
            x + near.box[0] * drawWidth,
            y + near.box[1] * drawHeight,
            near.box[2] * drawWidth,
            near.box[3] * drawHeight,
          );
        }
      }
      frameId = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frameId);
  }, [pose, videoRef, fit, positionY, geometry, showSkeleton]);
  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 h-full w-full"
      aria-hidden
    />
  );
}
