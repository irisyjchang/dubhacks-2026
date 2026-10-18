# iMessage video analysis through the Skate Coach API

Set `MESSAGING_AGENT_API_URL` in `.env` to the current HTTPS tunnel from the
backend owner, then restart `npm run photon`. The URL stays in configuration;
it is not hardcoded into the integration. The API requires no key according to
the supplied messaging-agent guide. Uploads send the video to that external API.

With this variable set, incoming iMessage videos use the hosted API in place of
the local port-8001 pipeline. The local web upload service remains available.

The Photon listener also imports every completed video in the hosted web
library (`GET /app/history`, then `GET /agent/analysis/{id}`) into MongoDB.
It backfills existing reports on startup, checks every 30 seconds, and refreshes
before answering questions or building voice context. Upload timestamps determine
the default video, so backfills and slow processing cannot make an older upload
appear newest. Repeated syncs and restarts reuse saved reports. Processing and
failed uploads are excluded from report memory; the coach identifies when the
newest upload does not yet have a completed report. If the library or newest
completed report cannot be refreshed, text answers ask the user to retry instead
of silently answering from an outdated report. Unavailable older reports are
retried without blocking the latest report. The full library catalog is also
persisted in MongoDB, including entries whose report endpoint is unavailable.

This is a **shared library**: all uploads feed the coach belonging to the configured
`PHOTON_ALLOWED_SENDER`, including its authorized groups. Reports are stored, not
raw video files. No unsolicited report notifications are sent by this import.
Set `PHOTON_LIBRARY_SYNC=false` to disable it. Keep `MESSAGING_AGENT_API_URL`
pointed at the analysis backend (the same origin as the website's
`NEXT_PUBLIC_SKATE_API_URL`), rather than the separate website tunnel.

1. Send one MP4, MOV, M4V, AVI, MKV, or WebM video under 199 MB in the owner's
   DM or the coaching group. Current group membership, STOP, and mute rules
   are checked before processing and again before sending results.
2. The agent acknowledges the upload, then calls `POST /agent/analyze` with
   `video`, `program_type`, and `perceptron_track`. If the API returns `202`, the agent saves the job ID and polls
   `GET /agent/analysis/{id}` at the requested interval (normally 15 seconds),
   for up to 20 minutes. This API supports longer programs; the local pipeline's
   former 30-second limit does not apply here.
3. The response's `message` is sent unchanged as text. The analysis ID is
   stored per conversation, and the returned report is also saved to the
   existing coach memory for ordinary questions. Model scores and move labels
   remain predictions rather than official judging.
4. Reply `3`, `move 3`, or `tell me about the third one`. The agent calls
   `POST /agent/move` with that chat's analysis ID and `view: "normal"`, sends
   its message unchanged, then attaches the original move MP4. Reply
   `skeleton` for the same move with a pose overlay and tracking box, or
   `skeleton move 3` to choose a move directly. Reply `normal` or `original`
   to switch back. The selected view comes from the response's `video_url`.
   The agent offers the other view after sending each clip.
   A new video replaces only that chat's active analysis. If the API reports no
   numbered moves, the agent does not request move details.

Optional settings: `MESSAGING_AGENT_PROGRAM_TYPE=unk|sp|fs` and
`MESSAGING_AGENT_PERCEPTRON_TRACK=true|false`. Defaults match the supplied
guide: unknown program type and person tracking enabled.

Analysis responses and per-video upload GUIDs are saved under ignored
`.coach/messaging-agent/`. Delivery retries reuse saved text, attachments, and
stable Photon message keys. The same event is not re-analysed after its result
has been saved. Once a `202` job ID is saved, restarts resume polling without re-uploading
the video. A restart or timeout before receiving any job ID can still repeat
remote computation: the API has no documented idempotency guarantee. Transient HTTP/network failures retry once. Bad move
numbers return a range hint; an expired analysis asks for a new upload.

Videos are fetched only from the configured API origin, with redirects disabled
and a size limit. Credentials and pipeline error logs are never forwarded to
the chat. Temporary Cloudflare URLs change on restart; update the variable and
resend the clip if the server no longer recognizes its analysis ID.

This document's API is for video-analysis HTTP calls. It does not implement
telephone calls or joining FaceTime. The existing SIP voice integration is
separate.

Verification: `node --test scripts/messaging-agent.test.mjs`.
