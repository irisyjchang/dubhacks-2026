import { afterEach, beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { ApiError, delay, skateApi, waitForAnalysis } from "../src/lib/api.ts";

const originalFetch = globalThis.fetch;
const originalUrl = process.env.NEXT_PUBLIC_SKATE_API_URL;
const controller = () => new AbortController();
const done = { analysis_id: "clip123", status: "done", moves: [], score: 0 };
const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers });

beforeEach(() => {
  process.env.NEXT_PUBLIC_SKATE_API_URL = "https://api.example.test/";
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalUrl === undefined) delete process.env.NEXT_PUBLIC_SKATE_API_URL;
  else process.env.NEXT_PUBLIC_SKATE_API_URL = originalUrl;
});

test("uploads the video and selected options as multipart; immediate results need no poll", async () => {
  let calls = 0;
  globalThis.fetch = async (url, options) => {
    calls++;
    assert.equal(url, "https://api.example.test/app/analyze");
    assert.equal(options.method, "POST");
    assert.equal(options.body.get("video").name, "spin.mov");
    assert.equal(options.body.get("program_type"), "fs");
    assert.equal(options.body.get("perceptron_track"), "false");
    assert.equal(options.headers, undefined); // Browser adds the multipart boundary.
    return json(done);
  };
  const signal = controller().signal;
  const result = await skateApi.analyze(
    new File(["fixture"], "spin.mov"),
    "fs",
    false,
    signal,
  );
  assert.deepEqual(await waitForAnalysis(result, signal), done);
  assert.equal(calls, 1);
});

test("202 respects Retry-After and polls the same analysis ID to completion", async () => {
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(url);
    return urls.length === 1
      ? json({ analysis_id: "clip123", status: "processing" }, 202, {
          "Retry-After": "1",
        })
      : json(done);
  };
  const signal = controller().signal;
  const pending = await skateApi.analysis("clip123", signal);
  assert.equal(pending.retry_after_s, 1);
  let processing = 0;
  assert.deepEqual(
    await waitForAnalysis(pending, signal, () => processing++),
    done,
  );
  assert.equal(processing, 1);
  assert.deepEqual(
    urls,
    Array(2).fill("https://api.example.test/app/analysis/clip123"),
  );
});

test("does not retry processing failures and exposes the backend error", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json({ status: "failed", error: "No readable video frames" }, 422);
  };
  await assert.rejects(
    skateApi.analysis("bad", controller().signal),
    (e) =>
      e instanceof ApiError &&
      e.status === 422 &&
      e.message === "No readable video frames",
  );
  assert.equal(calls, 1);
});

test("a tunnel 5xx response retries once, including HTML errors", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return new Response("<html>Bad Gateway</html>", { status: 502 });
  };
  await assert.rejects(
    skateApi.history(controller().signal),
    (e) => e instanceof ApiError && e.status === 502,
  );
  assert.equal(calls, 2);
});

test("a transient connection failure retries and recovers", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    if (++calls === 1) throw new TypeError("Network failed");
    return json({ videos: [] });
  };
  assert.deepEqual(await skateApi.history(controller().signal), { videos: [] });
  assert.equal(calls, 2);
});

test("canceling an analysis stops pending polls", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json(done);
  };
  const task = controller();
  const waiting = waitForAnalysis(
    { analysis_id: "clip123", status: "processing", retry_after_s: 15 },
    task.signal,
  );
  task.abort();
  await assert.rejects(waiting, { name: "AbortError" });
  assert.equal(calls, 0);
  await assert.rejects(delay(1000, task.signal), { name: "AbortError" });
});

test("move requests encode IDs and use the selected view", async () => {
  globalThis.fetch = async (url) => {
    assert.equal(
      url,
      "https://api.example.test/app/moves/clip%2F123/2?view=skeleton_only",
    );
    return json({ videos: {} });
  };
  await skateApi.move("clip/123", 2, "skeleton_only", controller().signal);
});

test("missing API configuration gives an actionable error without a request", async () => {
  delete process.env.NEXT_PUBLIC_SKATE_API_URL;
  globalThis.fetch = async () => {
    assert.fail("No request should be made");
  };
  await assert.rejects(
    skateApi.history(controller().signal),
    /NEXT_PUBLIC_SKATE_API_URL/,
  );
});
