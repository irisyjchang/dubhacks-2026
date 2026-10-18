# Live coaching calls through Photon

This integration uses **Photon Spectrum stable** for the existing iMessage
number and **ElevenLabs Agents** for SIP audio, transcription, and speech.
It supports inbound coaching calls and an explicit outbound callback command.
In the default **hosted** mode, saved feedback and recent iMessage context are
uploaded to the hosted agent before calls. The running Photon listener checks
for changes every 15 seconds. This mode requires **no public HTTPS endpoint**.
Calls do not join the iMessage group as
a conference. This prototype restricts private call feedback to the configured
feedback owner. START/STOP detaches or reassigns the phone agent on the next
successful sync; it does not terminate an already active call. Hosted calls
cannot write goals or practice logs to MongoDB, and call transcripts are not
imported into iMessage history. Text those updates to save them. Context changes
during a call apply to subsequent calls.

## Prepare locally

```sh
npm run calls:plan
node --test scripts/photon-calls.test.mjs
```

The plan is safe to print: it omits keys, SIP passwords, and the webhook token.
Until provider provisioning and SIP routing are configured, live calling is **not enabled**.
`PHOTON_CALLS_ENABLED=false` is the default. Voice notes continue independently.

## Enable without hosting an HTTPS endpoint

1. Give the existing ElevenLabs API key Agents and phone-number read/write
   permissions. Voice synthesis permissions alone are insufficient. During the
   initial account check, both Agents and phone-number endpoints returned HTTP
   401 with `missing_permissions`.
2. Set `PHOTON_CALLS_MODE=hosted` in `.env` and run `npm run calls:setup`.
   This provisions an authenticated ElevenLabs agent and SIP trunk, loading the
   saved coaching context from MongoDB. It creates external resources and sends
   the Spectrum SIP credentials to ElevenLabs. The local config remains in the
   ignored `.coach/calling/config.json` file. No webhook tool is created.
3. Register the inbound SIP URI printed by setup in the Photon dashboard for
   the existing line: `sips:+16285027257@sip.rtc.elevenlabs.io:5061`.
4. Set `PHOTON_CALLS_ENABLED=true` and run `npm run photon`. Keep it running to
   sync new feedback and START/STOP. Call the existing coach number from the
   configured owner's phone. For a callback use `npm run calls:dial -- demo-1`.
5. Test two-way audio. Local context sync readiness is reported under
   `calling.ready`; it does not verify the dashboard's SIP route or phone audio.

All app traffic is outbound to the providers' HTTPS APIs; you do not host HTTPS
or expose a local port. The hosted agent retains its last snapshot if the local
listener stops or cannot sync. Pause while connected before shutting it down,
or unassign the phone agent directly in ElevenLabs. The inbound trunk restricts
callers, and browser/WebSocket sessions require agent authentication.

## Optional: enable live backend tools later

To allow the current coaching group's phone numbers in hosted mode, run
`npm run calls:allow-group`, then restart the listener. This reads and validates
the saved Photon group roster and verifies ElevenLabs retained the new caller
list. Shared voice context excludes private DM history and private journal notes.
If the live roster service is unavailable, `-- --saved-roster` explicitly uses
the last stored native group roster instead; it cannot confirm later removals.
Re-run after group membership changes; email-only participants need a phone
number in the group before they can be included. Explicit outbound callbacks
continue to target the feedback owner. Setup preserves the saved caller list.

Set `PHOTON_CALLS_MODE=webhook` to use the original live coach tool, which records
coaching exchanges and can save updates during the call. Then:

1. Point a public HTTPS tunnel or reverse proxy **only** at `127.0.0.1:8789`.
   Do not expose the coach's private port 8787. The call gateway serves only
   authenticated `POST /api/calls/coach` requests.
2. Set `CALLS_PUBLIC_URL=https://your-public-host` in `.env`. Keep the existing
   `ELEVENLABS_API_KEY`, `SPECTRUM_PROJECT_ID`, `SPECTRUM_PROJECT_SECRET`,
   `PHOTON_PHONE_NUMBER`, and `PHOTON_ALLOWED_SENDER`. The ElevenLabs key needs
   Agents, tools, and phone-number permissions, in addition to voice synthesis.
3. Run `npm run calls:setup`. This **creates external resources**: a webhook
   tool, a voice agent, and an imported SIP trunk in ElevenLabs. It sends the
   Spectrum project credentials to ElevenLabs for outbound SIP authentication.
   Resource IDs and a generated bearer token are saved in ignored
   `.coach/calling/config.json` with owner-only file permissions. Keep this file
   between restarts; do not commit or share it. Re-running updates the owned
   tool and agent using their saved IDs. If a creation request times out, check
   ElevenLabs before rerunning to avoid creating duplicate resources.
4. In the Photon dashboard, open the **existing Spectrum project and iMessage
   line**, then register the inbound URI printed by setup, for example
   `sips:+16285027257@sip.rtc.elevenlabs.io:5061`.
   Leave inbound digest credentials empty; the ElevenLabs imported trunk
   restricts inbound numbers to the feedback owner. Spectrum's outbound trunk
   uses TLS on `sip.spectrum.photon.codes:5061`, with SIP registration disabled.
5. Set `PHOTON_CALLS_ENABLED=true`, then start/restart `npm run photon`.
   Send START in iMessage if coaching is paused. Call the coach number from the
   owner's phone. Ask about saved feedback, hang up, then continue in iMessage.
6. For an explicitly requested callback, run `npm run calls:dial -- demo-call-1`.
   Only the configured feedback owner is dialled. Reusing a request ID never
   attempts a second call, even after an ambiguous network failure. Check call
   history before using a new ID. This command incurs normal provider call usage.

Local gateway readiness appears under `calling` in
`GET /api/coach/messaging`. This verifies only the local HTTP listener; it does
not certify the Photon dashboard route or two-way phone audio. Verify both
inbound and outbound audio on real phones before marking calling live.

SIP signaling uses TLS, while Spectrum currently supports unencrypted RTP audio
only. Accordingly, the imported trunk sets media encryption to disabled. Setting
SRTP to required would prevent compatible audio. Phone identity relies on the
telephony provider's caller metadata; it is not an independent identity proof.
Webhook retries are coalesced in process; restart during a tool request can
repeat a conversation entry. Callback claims persist across restarts.

Contracts used:

- [Spectrum Voice](https://photon.codes/docs/spectrum-ts/providers/voice)
- [Spectrum inbound calls](https://photon.codes/docs/spectrum-ts/providers/voice/inbound-calls)
- [Spectrum outbound calls](https://photon.codes/docs/spectrum-ts/providers/voice/outbound-calls)
- [ElevenLabs SIP trunking](https://elevenlabs.io/docs/eleven-agents/phone-numbers/sip-trunking)
- [ElevenLabs outbound call API](https://elevenlabs.io/docs/eleven-agents/api-reference/sip-trunk/outbound-call)

The API payloads are based on these published contracts. Local tests mock the
voice provider. Remote provisioning, metadata propagation through Spectrum SIP,
and actual two-way audio still need verification after provider permissions and
SIP routing are configured. Only webhook mode needs a public HTTPS endpoint.
