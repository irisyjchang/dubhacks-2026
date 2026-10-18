Local text coach
===============

The active iMessage video path can use the hosted Skate Coach API via
`MESSAGING_AGENT_API_URL`. It returns the backend's move list and handles
numbered move follow-ups with normal and skeleton videos. See
[messaging API setup](MESSAGING-API.md). The local backend flow below remains
the fallback when that URL is unset.

Send one video (up to 30 seconds / 199 MB) to the Photon number in iMessage.
Run `npm run imessage-video-server` alongside `npm run photon`: the dedicated
loopback service on port 8001 runs `backend/coaching/run_spin_coach.py`, remuxes
its annotated `feedback.mp4` to a real `feedback.mov`, and saves the full backend
report to the existing MongoDB coach memory. Photon uploads the resulting MOV
and replies in the originating conversation, followed by a report excerpt.
Ask follow-up questions in that same chat to discuss the saved backend report.
The upload has no confirmed technical element, so the backend uses its general
skating review instead of guessing a spin/jump label. Existing web uploads on
port 8000 continue separately. Processing jobs live under `outputs/imessage_jobs`.
Group members may upload while they remain in the current owner-containing group;
private uploads are restricted to the feedback owner. STOP and group mute are
checked again before delivering results. Receipts persist the Python job,
uploaded video GUID, and delivery stage so retries reuse the same attachment
and stable iMessage send key. Python in-memory jobs still reset on service restart;
clips interrupted by that restart need to be resent.

Live phone calling is implemented through Photon Spectrum SIP and ElevenLabs
Agents. See [CALLING.md](CALLING.md) for setup, local testing, and activation.

The active connection is regular Photon / Spectrum (not the 2.0 beta).
Set `PHOTON_CONNECTION=spectrum`, `SPECTRUM_PROJECT_ID`, and
`SPECTRUM_PROJECT_SECRET` for the account that owns the dedicated line.
The configured AI line is dedicated iMessage **+1 628-502-7257**, with
`PHOTON_CHANNEL=imessage`. The listener
selects this exact Photon agent and refuses to send from any other number.
If this number is not visible to the configured project, the local preview stays
available and phone delivery waits for the correct project configuration.

Text START to enable new-report follow-ups, GOAL plus a focus to save it, PLAN
for a short practice session, DONE plus a note to log practice, COACH plus a
human coach note to remember that advice, CHECKIN plus a note to record how
practice felt, PROGRESS to compare two attempts, TIMELINE for recent feedback,
or SHARE for a copyable human-coach summary. STOP pauses replies and follow-ups
across restarts. /ai clears chat memory while preserving goals and notes.

PLAN uses two independent role calls (evidence reviewer and practice planner)
and a final conversational coach. Report notifications are enqueued only for a
new report after opt-in; retrying the same upload does not enqueue another.
MongoDB stores preferences and goals in `coach_athletes`, user-attributed notes
in `coach_journal`, outbound reply bodies in `photon_replies`, and successful
Photon event sequence checkpoints in `photon_checkpoints`.

The Spectrum listener uses the official cloud iMessage SDK and its gRPC
reconnection/catch-up. Replies use the Advanced iMessage transport with stable
clientMessageId keys and a MongoDB outbox. It verifies the chosen dedicated line
belongs to this project, ignores other lines, and checks current chat membership
again before every send. The optional beta adapter remains in photon-beta.mjs;
it is used only with PHOTON_CONNECTION=beta.
`GET /api/coach/messaging` reports live readiness, goal, opt-in, and recent
notes; the upload app reads it at `/api/text-coach`. No credentials are exposed.
See [the demo walkthrough](../PHOTON-DEMO.md) for the product narrative.

Start both processes from the project directory:

Set `MONGODB_URI` in `.env` to your Atlas connection string and optionally set
`MONGODB_DB=figure_skating_coach`. Use a database user with read/write access
to that database and permit this computer in your Atlas network access rules.
The URI stays on the server. A local MongoDB instance is also supported at
`mongodb://127.0.0.1:27017`.

```sh
npm run photon
npm run dev -- --host 127.0.0.1
```

Open http://127.0.0.1:5173 and finish a video analysis. The status above the
metrics confirms when the latest results have synced. Once the dedicated line is connected, text the configured Photon number from PHOTON_ALLOWED_SENDER and ask
about your latest attempt. Direct replies are restricted to that student.
Everyone in the feedback owner’s group may participate; there is no coach role
or participant allowlist.
`/stop` pauses direct replies; `/ai` restarts the direct conversation.

For spin reports and the group preview, also run `.video-venv/bin/python webapp.py`
and open http://127.0.0.1:8000. The preview saves messages in `coach_rooms` and
`coach_room_messages`; the participant selector is for local testing only.
`GET/POST /api/coach/rooms`, `GET /api/coach/rooms/:id`, and
`POST /api/coach/rooms/:id/messages` operate on preview rooms. Native rooms
cannot accept browser-supplied participant identities. Native roles are
verified against Photon’s current Space membership for every message.

The browser sends summary metrics and joint-angle comparisons near marked
takeoff and landing through the Vite development proxy to a loopback-only
service on port 8787. MongoDB stores analyses in `analyses` and question/reply
exchanges in `coach_conversations`, scoped to the configured sender. No video
is uploaded. Sync retries are deduplicated with an atomic upsert. The app lists
the 20 newest analyses; the coach receives up to five recent analyses and six
recent exchanges. Both web and iMessage use this same stored conversation.
`/ai` starts a new conversation in both channels. There is no account system
or multiuser backend.

Existing `.coach/latest.json` analyses are imported on startup with idempotent
upserts. The original file is preserved. New writes go only to MongoDB.

Python spin reports
-------------------

The Python upload flow (`webapp.py`, normally on http://127.0.0.1:8000)
automatically publishes completed `coaching_report.md` content, timestamped
rule findings, and report provenance to the running coach service. The report
is saved in MongoDB and supplied to the AI for both web and iMessage questions.
Partial model output stays marked partial; local rules stay identified as
local rules. Video frames, API keys, and raw model-request files are not sent
to this service. Feedback text and questions are sent to OpenAI when chatting.

Start `npm run photon` before analyzing. If it is offline, the completed video
and report remain available and the upload page offers "Share report with text
coach" to retry without reprocessing. `/api/jobs/<id>/coach` is the local retry
endpoint. `COACH_SYNC_URL` may override the loopback endpoint for another local
port. Only new completed uploads are shared automatically; earlier job results
can be shared with the retry button while that upload server still has the job.

From the configured phone, ask "What should I change with my arms?" or "What
did my report say about the middle of my spin?". The coach answers from the
latest saved feedback, with timestamps when available. If a newer metrics-only
analysis exists, it does not hide the latest coaching report.

Feedback timeline
-----------------

The upload page and React coach panel show "Your feedback timeline" from
MongoDB. Entries show the saved analysis date, recording name, headline, report
provenance, and full feedback on demand. The upload page also downloads the
feedback as Markdown. Older entries load in pages of ten; the cursor includes
date and ID so matching timestamps do not cause skipped or duplicate entries.
Sync retries do not create duplicate timeline entries. Only feedback-bearing
spin reports appear; videos and metrics-only analyses are not timeline items.

`GET /api/coach/timeline?before=<cursor>` returns summaries plus `nextCursor`.
`GET /api/coach/timeline/<id>` reads the full stored feedback. Both queries are
scoped to PHOTON_ALLOWED_SENDER. The Python upload app proxies these at
`/api/feedback` and `/api/feedback/<id>`. They work after upload jobs reset,
because reopening feedback does not require the original video or job record.
This remains the single configured user's local prototype, not a multiuser
authentication system.

The local app has a figure skating coach panel for feedback and questions,
clickable measurement timestamps, and a recent-attempt list. Timestamp buttons
seek both loaded videos to their corresponding measured movement phase.
If an old analysis is restored, the newest saved attempt remains the text
coach's latest result. It does not create a duplicate history entry.

The analyzer currently estimates airtime, body rotation, and airtime-derived
height. It does not measure skateboard rotation or produce a trick score.
The coach prompt explains these limitations and instructs the model not to
invent absent results. Joint differences are descriptive measurements, not
validated diagnoses of technique problems. Ghost overlays and automatic phase detection are not implemented. Goals and
group coaching are supported; the local group preview is a
single-user development tool, not an authenticated coach dashboard.

Secrets stay in the ignored `.env`, with OPENAI_API_KEY, SPECTRUM_PROJECT_ID,
SPECTRUM_PROJECT_SECRET, PHOTON_PHONE_NUMBER, PHOTON_ALLOWED_SENDER, and MONGODB_URI.
The optional beta adapter uses PHOTON_API_KEY and PHOTON_PROJECT_ID. Never prefix
these secrets with VITE_ or commit them. Rotate keys shared in chat.

Verification: `npm run type-check`, `npm run build`, and
`node --env-file=.env --test scripts/coach-state.test.mjs scripts/coach-evidence.test.mjs scripts/coach-database.test.mjs`.
The HTTP tests use an isolated test store and mock model responses. The MongoDB
connection test performs a read-only ping; it never drops a database.

Group setup and the dedicated line configuration are documented in [PHOTON-DEMO.md](../PHOTON-DEMO.md).
Every human in the current group has the same member role. No PHOTON_COACH_HANDLE
or PHOTON_GROUP_MEMBERS settings are needed. Replies use the live group roster,
and the feedback owner must be in the group to link it to their reports.
Only the owner can receive private DM replies. Historical coach/guest labels and
approval decisions have no authority in the current group flow.

Native conversation feedback
----------------------------

Regular Spectrum replies now thread to the incoming Photon message, including
group questions, while keeping the existing stable outbox send keys. New direct and addressed group
questions show a read receipt and a refreshed typing indicator during answer
generation. Typing clears on success or failure. Paused questions, unauthorized
senders, and already-submitted events do not start typing. Group read receipts
are sent only when the AI sends a reply; ordinary group conversation does not
trigger presence updates. Presence failures do not block a coaching answer.
These use the installed Advanced iMessage SDK's `replyTo`, `markRead`, and
`setTyping` APIs. Restart `npm run photon` to load the changes. Validate on phones
by asking a direct question and an `AI,` group question; automated tests mock
Photon and do not establish live delivery.

Group commands PLAN, PROGRESS, TIMELINE, and SHARE now use the training-command
handlers rather than the generic question handler. LATEST requests the latest
report through the shared-evidence responder. HELP lists group commands. Use
plain commands, slash commands, or an `AI,` prefix. Group answer generation shows
a typing indicator; muted rooms, ordinary conversation, and replayed answers
do not start typing. Personal goal and journal writes remain DM commands.

ElevenLabs voice notes
---------------------

Set ELEVENLABS_API_KEY in the ignored .env file. ELEVENLABS_VOICE_ID defaults
to George (JBFqnCBsd6RMkjVDRZzb); ELEVENLABS_MODEL_ID defaults to
eleven_multilingual_v2. Restart the Photon listener after configuration.
Every eligible direct or group coaching reply is sent as a native audio
message instead of text when speech generation and upload succeed. Speech uses the saved reply
text, sent to ElevenLabs. Reaction-only acknowledgments and report notifications
remain outside voice selection. STOP/START and direct HELP stay text.
Choice and uploaded audio GUID are saved under .coach/voice-notes, preserving
the format and attachment on send retries and restarts. Missing credentials or
synthesis/upload failures fall back to text; ambiguous delivery failures retry
the same audio and stable send key rather than sending a second text reply.
Tests mock ElevenLabs and Photon; live audio delivery requires verification.

Native voice notes omit replyTo because the Photon IMAgentKit send path rejects
audio-message mode combined with a thread target. Text replies remain threaded.

Speech MP3 output is converted to mono AAC in an M4A container, then fully
decoded and checked for a positive duration before upload. This requires
FFMPEG_PATH, ffmpeg on PATH, or the existing .video-venv imageio_ffmpeg binary.
Invalid audio falls back to text. New messages use the corrected format; saved
older attachment GUIDs retain their original format for idempotent retries.

iMessage video uploads
---------------------

Users may continue uploading through the existing web pages, or attach a clip
directly to the dedicated iMessage line. Start `npm run video-server` and
`npm run photon` from this directory. The video-server command loads the ignored
.env file; set NVIDIA_API_KEY there for model coaching. IMESSAGE_VIDEO_MODE
defaults to nvidia; explicitly select local for disclosed rule-only analysis.
Existing direct Python startup remains supported.

Send one MOV, MP4, M4V, WebM, or AVI clip, under 199 MB and 30 seconds, from
PHOTON_ALLOWED_SENDER. The bot acknowledges it, downloads the canonical Photon
attachment by GUID, submits it to the same Python job pipeline, and waits for
MongoDB feedback sync before sending the report excerpt back. The excerpt uses
the current voice-note setting; the full report is in TIMELINE/the web timeline.
PROGRESS compares it with earlier saved reports. No new timeline store is used.

In native groups, only the configured feedback owner can add a video to their
progress. Other members can continue discussing shared feedback. STOP and group
MUTE AI suppress uploads/replies. Uploading a clip explicitly requests analysis;
it does not opt into future unsolicited report notifications. Captions remain
part of the received event; the measurement pipeline analyzes the clip itself.

The local receipts in .coach/imessage-videos retain event IDs, route, filename,
and Python job IDs for retries/restarts. Downloads run in the background with
at most two active tasks; the Python worker processes one clip at a time.
Repeated Photon events reuse their job. If the Python server restarts during a
job, the bot asks for the clip again because that server's jobs are in memory.
Completed reports remain in MongoDB. Raw videos and generated artifacts remain
in outputs/web_jobs under the existing local retention behavior. No automatic
deletion or multiuser account system is introduced.
