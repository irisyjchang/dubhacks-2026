export type Point = [number, number];
export function poseFrameAt<T extends { t: number }>(frames: T[], time: number, fps: number): T | undefined {
  let lo = 0, hi = frames.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (frames[mid].t < time) lo = mid + 1;
    else hi = mid;
  }
  const before = frames[lo - 1], after = frames[lo];
  const frame = !before ? after : !after ? before : time - before.t <= after.t - time ? before : after;
  // Never stretch an old detection across a missing section or past the clip.
  return frame && Math.abs(frame.t - time) <= 1.5 / (fps || 30) ? frame : undefined;
}

export function hasTrackedBody(kp: [number, number, number][], threshold: number): boolean {
  return kp.slice(5).filter(p => p.every(Number.isFinite) && p[2] >= threshold).length >= 4;
}
/** Interior angle at b, in pixel space. Degenerate limbs have no measurable angle. */
export function angleAt(a: Point, b: Point, c: Point): number | null {
  const u = [a[0] - b[0], a[1] - b[1]];
  const v = [c[0] - b[0], c[1] - b[1]];
  const length = Math.hypot(...u) * Math.hypot(...v);
  if (length < 1e-8) return null;
  return (
    (Math.acos(
      Math.max(-1, Math.min(1, (u[0] * v[0] + u[1] * v[1]) / length)),
    ) *
      180) /
    Math.PI
  );
}
