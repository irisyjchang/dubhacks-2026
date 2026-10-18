import { test } from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { readFile } from "node:fs/promises";

const source = await readFile(
  new URL("../public/sw.js", import.meta.url),
  "utf8",
);
function worker(overrides = {}) {
  const listeners = new Map();
  vm.runInNewContext(source, {
    URL,
    self: {
      location: { origin: "https://skate.example" },
      addEventListener: (name, callback) => listeners.set(name, callback),
      skipWaiting() {},
      clients: { claim() {} },
    },
    caches: {},
    ...overrides,
  });
  return listeners;
}

test("authentication, session pages, RSC and API requests are never cached", () => {
  const listeners = worker();
  for (const path of [
    "/",
    "/login",
    "/signup",
    "/sign-in",
    "/sign-in/sso-callback",
    "/sign-up",
    "/__clerk/v1/client",
    "/api/session",
    "/analysis?_rsc=abc",
  ]) {
    const request = new Request(`https://skate.example${path}`);
    listeners.get("fetch")({
      request,
      respondWith() {
        assert.fail(`Must not intercept ${path}`);
      },
    });
  }
});

test("video ranges and non-GET requests bypass the image cache", () => {
  const listeners = worker();
  for (const request of [
    new Request("https://skate.example/media/poster.jpg", {
      headers: { Range: "bytes=0-99" },
    }),
    new Request("https://skate.example/media/poster.jpg", { method: "POST" }),
    new Request("https://cdn.example/media/poster.jpg"),
  ]) {
    listeners.get("fetch")({
      request,
      respondWith() {
        assert.fail("Must not intercept this request");
      },
    });
  }
});

test("activation removes only old SkateCue caches", async () => {
  const removed = [];
  const listeners = worker({
    caches: {
      keys: async () => ["skatecue-pwa-v2", "skatecue-pwa-v3", "other-app"],
      delete: async (name) => removed.push(name),
    },
  });
  let finished;
  listeners.get("activate")({
    waitUntil(promise) {
      finished = promise;
    },
  });
  await finished;
  assert.deepEqual(removed, ["skatecue-pwa-v2"]);
});
