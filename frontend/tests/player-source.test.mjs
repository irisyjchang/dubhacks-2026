import { test } from "node:test";
import assert from "node:assert/strict";
import { cropSource, isPortraitCrop } from "../src/lib/player-source.ts";
const analysis = { video_url: "full.mp4", moves: [{ n: 1, segment: { start_s: 2.5 } }], single_move: { videos: { crop: "inline-crop.mp4" } } };

test("only 9:16 video dimensions enable immersive crop rendering", () => {
  assert.equal(isPortraitCrop(1080, 1920), true);
  assert.equal(isPortraitCrop(608, 1080), true);
  assert.equal(isPortraitCrop(606, 1080), true);
  assert.equal(isPortraitCrop(958, 774), false);
  assert.equal(isPortraitCrop(1080, 1080), false);
  assert.equal(isPortraitCrop(1920, 1080), false);
  assert.equal(isPortraitCrop(0, 0), false);
  assert.equal(isPortraitCrop(NaN, 1920), false);
});

test("the whole-clip API crop takes precedence with its matching pose", () => {
  const pose = { width: 100 };
  assert.deepEqual(cropSource({ ...analysis, player_view: { cropped: true, crop_video_url: "whole-crop.mp4", pose } }, { videos: { crop: "move-crop.mp4" } }), { src: "whole-crop.mp4", offset: 0, pose });
});

test("the move crop uses the API's padded segment offset and its own pose", () => {
  const detail = { move: { n: 1, segment: { start_s: 1.9 } }, videos: { crop: "move-crop.mp4" }, pose: { width: 200 } };
  assert.deepEqual(cropSource(analysis, detail), { src: "move-crop.mp4", offset: 1.9, pose: detail.pose, move: 1 });
});

test("inline single-move crop remains usable without detail or full-frame pose", () => {
  const crop = cropSource({ ...analysis, pose: { width: 1920 } });
  assert.deepEqual(crop, { src: "inline-crop.mp4", offset: 2, move: 1 });
  assert.equal(crop.pose, undefined);
  assert.equal(cropSource({ ...analysis, moves: [{ n: 1, segment: { start_s: 0.2 } }] }).offset, 0);
});

test("does not invent a crop when the API does not supply one", () => {
  assert.equal(cropSource({ video_url: "full.mp4", moves: [] }), null);
  assert.equal(cropSource({ ...analysis, moves: [analysis.moves[0], analysis.moves[0]] }), null);
});
