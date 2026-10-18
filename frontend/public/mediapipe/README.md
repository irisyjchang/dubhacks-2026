Local assets for the missing-pose fallback. Video frames are processed in the browser's pose worker.

- `wasm/*`: copied from the pinned `@mediapipe/tasks-vision@0.10.32` npm package (Apache-2.0). Keep these in sync if upgrading the dependency.
- `pose_landmarker_lite.task`: Google's MediaPipe pose landmarker lite float16, version 1, from https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task

The worker loads these same-origin assets only when a displayed frame has insufficient API keypoints. It maps MediaPipe's 33 landmarks to the existing COCO-17 overlay layout.
