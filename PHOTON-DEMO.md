# Text-first skating companion · Photon Spectrum

The product loop is **analyze → understand → choose a goal → practice → return
with another attempt**. Photon is the coaching surface between sessions.
The active connection uses regular Photon / Spectrum in project **Hackathon6**.
Its dedicated line and native coaching group have been verified through the API.
The configured AI line is dedicated iMessage on **+1 628-502-7257**, with
feedback owner **+1 905-462-9158**.
The listener uses only this exact agent. It waits if the number is not assigned
to the configured Photon project; it never falls back to another line.

Use the **Skating group + AI** local preview at http://127.0.0.1:8000.
It uses the saved video reports and persists group messages in MongoDB.
The role selector simulates both humans locally and sends no phone messages.
Everyone currently in the owner's iMessage group can interact with the AI.
There are no coach/guest roles, individual allowlists, or approval commands.
The app verifies the real group roster and still keeps private DMs out of the group.

Invite the AI with `AI, what should we focus on?`, `/ai`, `/plan`, or `/progress`.
Ordinary human conversation is stored without an AI interruption. Anyone can
use `MUTE AI`/`UNMUTE AI` (or STOP/START) to control participation for this group.

The listener reopens the existing group after restart. You can also start a new
iMessage group containing the feedback owner, AI number, and anyone you want to invite.
`PHOTON_CHANNEL=imessage` selects the line.

## What to demonstrate

| Track theme | Working behavior |
| --- | --- |
| A companion with social context and tone | The coach responds to the skater's expressed frustration or excitement, remembers their goal, and offers a manageable next step. It does not infer emotions from video. |
| Agents working toward a shared goal | PLAN runs two independent LLM role calls—an evidence reviewer and practice planner—then a conversational coach synthesizes their advice against the original report. |
| Humans and AI collaborating | The skater can save a human coach's advice with COACH, carry it into subsequent reviews, and use SHARE for a copyable handoff. Notes remain attributed to the user; no messages are sent to another person. |
| An agent in everyday messaging | The Spectrum cloud SDK receives iMessage over gRPC with reconnection/catch-up. A MongoDB outbox reuses saved answers; stable send keys prevent repeated logical sends. The sender is pinned to the configured dedicated line. |
| A relationship across practice sessions | Goals, practice logs, feelings check-ins, human coach notes, and feedback history persist in MongoDB. New-report texts follow START opt-in and honor durable STOP. |

## Three-minute demo

1. Open the upload page at http://127.0.0.1:8000. Show the saved real report and
   its timeline. Do not fabricate a second performance.
2. Once the line is connected, text **START** to **+1 628-502-7257**, then **GOAL keep my forward arm reach consistent**.
3. Ask **What is your take on my arm position?** The answer should identify the
   actual recording, cite the relevant interval, and separate observation from
   the coach's interpretation.
4. Text **PLAN**. The evidence reviewer and practice planner inform a short
   next session with a focus, cue, drill, and video self-check.
5. Say **I'm feeling frustrated that this isn't improving**. Show how the reply
   acknowledges the feeling without inventing a measured regression.
6. Text **COACH preserve the forward reach; don't pull my arms in**, then
   **DONE five slow entries**. Refresh the app's coaching card to show the saved
   goal and notes.
7. Analyze a new, genuine attempt. A follow-up text announces the new report
   and reconnects it to the saved goal. Ask **PROGRESS** to compare the last two
   reports. With only one report, the coach explains that improvement cannot
   yet be measured.

**SHARE** prepares a short first-person summary to show a human coach.
**TIMELINE** lists recent reports. **STOP** pauses replies and new-report texts;
**START** resumes. **/ai** resets the conversation without deleting goals or
practice notes. It does not opt back into report notifications after STOP.

## Scope and evidence

This uses the regular Photon **Spectrum** cloud SDK with a project ID and secret.
The beta adapter remains available but is inactive. Setup:
https://photon.codes/docs/spectrum-ts/getting-started and
https://photon.codes/docs/spectrum-ts/providers/imessage/connection-and-routing.
The active account is the regular dashboard account; this integration does not
claim to use the 2.0 beta platform.

The plan's roles are LLM interpretations, not separate measurement systems.
Human coach collaboration includes durable notes, a copyable handoff, a local
group preview, and a native group handler. Native iMessage delivery requires the
dedicated number to be visible to the configured project. No successful phone
group delivery is claimed until it has been tested on the phones.
Live voice calling has an optional Spectrum SIP / ElevenLabs integration; see
[calling setup](scripts/CALLING.md). Hosted mode needs no public HTTPS endpoint.
Provider permissions, inbound SIP routing, and real phone audio verification
are still required before calling is live. This remains a single-skater local
prototype. The coach has written reports, not direct video vision; uncertain
findings, partial reports, and unmeasured skating properties stay identified.
