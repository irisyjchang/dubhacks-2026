import { FilesetResolver, PoseLandmarker } from "@mediapipe/tasks-vision";

// Adapt MediaPipe's 33 landmarks to the API's COCO-17 joint order.
const COCO = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];
let detector: PoseLandmarker | undefined;
self.onmessage = async ({ data }: MessageEvent) => {
  if (data.type === "init") {
    try {
      const files = await FilesetResolver.forVisionTasks(`${self.location.origin}/mediapipe/wasm`);
      detector = await PoseLandmarker.createFromOptions(files, {
        baseOptions: { modelAssetPath: `${self.location.origin}/mediapipe/pose_landmarker_lite.task`, delegate: "CPU" },
        runningMode: "IMAGE",
        numPoses: 1,
        minPoseDetectionConfidence: 0.35,
        minPosePresenceConfidence: 0.35,
      });
      self.postMessage({ type: "ready" });
    } catch {
      self.postMessage({ type: "error" });
    }
    return;
  }
  const bitmap = data.bitmap as ImageBitmap;
  try {
    const points = detector?.detect(bitmap).landmarks[0];
    self.postMessage({
      type: "frame", time: data.time,
      kp: points ? COCO.map(i => [points[i].x, points[i].y, points[i].visibility ?? 0]) : [],
    });
  } catch {
    self.postMessage({ type: "error" });
  } finally {
    bitmap.close();
  }
};
