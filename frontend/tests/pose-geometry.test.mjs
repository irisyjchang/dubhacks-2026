import { test } from "node:test";
import assert from "node:assert/strict";
import { angleAt } from "../src/lib/pose-geometry.ts";
test("joint angles use pixel dimensions, including straight and right angles", () => {
  assert.equal(angleAt([0, 1], [0, 0], [1, 0]), 90);
  assert.equal(angleAt([-1, 0], [0, 0], [1, 0]), 180);
  assert.ok(Math.abs(angleAt([2, 1], [0, 0], [1, 0]) - 26.565051177) < 1e-6);
});
test("coincident keypoints do not produce a misleading angle", () => {
  assert.equal(angleAt([0, 0], [0, 0], [1, 1]), null);
});
