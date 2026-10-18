export type Point = [number, number];
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
