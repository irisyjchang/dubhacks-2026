import { test } from "node:test";
import assert from "node:assert/strict";
import { angleAt, poseFrameAt, hasTrackedBody } from "../src/lib/pose-geometry.ts";
test("joint angles use pixel dimensions, including straight and right angles", () => {
  assert.equal(angleAt([0, 1], [0, 0], [1, 0]), 90);
  assert.equal(angleAt([-1, 0], [0, 0], [1, 0]), 180);
  assert.ok(Math.abs(angleAt([2, 1], [0, 0], [1, 0]) - 26.565051177) < 1e-6);
});
test("coincident keypoints do not produce a misleading angle", () => {
  assert.equal(angleAt([0, 0], [0, 0], [1, 1]), null);
});

test("pose selection uses timestamps for sparse frames and backwards seeks", () => {
  const frames = [{ t: 0 }, { t: 0.1 }, { t: 0.2 }];
  assert.equal(poseFrameAt(frames, 0.19, 30), frames[2]);
  assert.equal(poseFrameAt(frames, 0, 30), frames[0]);
  assert.equal(poseFrameAt(frames, 0.8, 30), undefined);
  assert.equal(poseFrameAt([], 0, 30), undefined);
});

test("empty API detections trigger local tracking instead of a blank overlay", () => {
  const missing = Array.from({ length: 17 }, () => [-1.52, 0, 0]);
  assert.equal(hasTrackedBody(missing, 0.1), false);
  assert.equal(hasTrackedBody(Array.from({ length: 17 }, () => [0.5, 0.5, 0.9]), 0.35), true);
  assert.equal(hasTrackedBody(Array.from({ length: 17 }, () => [NaN, 0.5, 0.9]), 0.35), false);
});
