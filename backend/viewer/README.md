# viewer

Skeleton overlay + predicted element timeline for one clip.

    python viewer/build.py VIDEO -o outputs/viewer/NAME          # runs convert + predict + ffmpeg
    python viewer/build.py VIDEO -o outdir --npy clip.npy        # reuse skeleton (predict is still rerun unless --pred given)
    python viewer/build.py VIDEO -o outdir --npy clip.npy --pred pred.json   # pred.json must include frame_probs
    open outputs/viewer/NAME/index.html

Data is inlined into index.html, so file:// works (video.mp4 sits beside it). Avoid `python -m http.server`: it has no HTTP range support, so the browser cannot seek the video.
Controls: Space play/pause, Left/Right frame step, click timeline or element to seek.
Rotation is baked into video.mp4 by ffmpeg so skeleton pixel coords match displayed pixels.

## Upload UI

    convert/.venv/bin/python viewer/app.py   # then open http://localhost:8000

Drop a clip; it runs build.py in the background and opens the viewer when done. Uploads go to outputs/uploads/.
