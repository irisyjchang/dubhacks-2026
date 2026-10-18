export type VideoFrame = { time: number; image: string };

/** Decode the selected clip without seeking the visible player. */
export async function extractVideoFrames(
  src: string,
  signal: AbortSignal,
  timestamps?: readonly number[],
): Promise<VideoFrame[]> {
  const video = document.createElement("video");
  video.crossOrigin = "anonymous";
  video.muted = true;
  video.playsInline = true;
  video.preload = "auto";
  function waitFor(event: string) {
    return new Promise<void>((resolve, reject) => {
      const cleanup = () => {
        clearTimeout(timeout);
        video.removeEventListener(event, done);
        video.removeEventListener("error", failed);
        signal.removeEventListener("abort", aborted);
      };
      const done = () => {
        cleanup();
        resolve();
      };
      const failed = () => {
        cleanup();
        reject(new Error("Video preview unavailable"));
      };
      const aborted = () => {
        cleanup();
        reject(new DOMException("Aborted", "AbortError"));
      };
      const timeout = setTimeout(failed, 15000);
      video.addEventListener(event, done, { once: true });
      video.addEventListener("error", failed, { once: true });
      signal.addEventListener("abort", aborted, { once: true });
      if (signal.aborted) aborted();
    });
  }
  try {
    const loaded = waitFor("loadeddata");
    video.src = src;
    video.load();
    await loaded;
    if (
      !Number.isFinite(video.duration) ||
      !video.videoWidth ||
      !video.videoHeight
    )
      return [];
    const canvas = document.createElement("canvas");
    const scale = Math.min(1, 220 / video.videoWidth, 220 / video.videoHeight);
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const context = canvas.getContext("2d");
    if (!context) return [];
    const frames: VideoFrame[] = [];
    const times = timestamps?.length
      ? timestamps
      : Array.from({ length: 7 }, (_, index) => (index / 7) * video.duration);
    for (const timestamp of times) {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      const time = Math.max(
        0,
        Math.min(video.duration - 0.01, timestamp),
      );
      if (Math.abs(video.currentTime - time) > 0.001) {
        const seeked = waitFor("seeked");
        video.currentTime = time;
        await seeked;
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      frames.push({ time, image: canvas.toDataURL("image/jpeg", 0.8) });
    }
    return frames;
  } finally {
    video.pause();
    video.removeAttribute("src");
    video.load();
  }
}
