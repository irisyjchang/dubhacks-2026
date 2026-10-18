# SkateCue frontend

Next.js App Router, React, TypeScript, and Clerk. Home, Analysis, and Library share one persistent video element in the root layout. This is a responsive full-browser interface, without a device frame.

## Run locally

Use Node.js 22.18+ (Node 24 recommended).

```bash
npm ci
cp .env.example .env.local
npm run dev
```

Set `NEXT_PUBLIC_SKATE_API_URL` to the current API base URL. The example contains the temporary Cloudflare tunnel supplied with the API guide. Restart development after changing it; rebuild production because public environment variables are bundled by Next.js. API hosts are configuration, never application source.

For authentication, connect the **existing** Clerk application with `npx clerk auth login`, `npx clerk link --app <app-id>`, and `npx clerk env pull`. Both `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and server-only `CLERK_SECRET_KEY` must be present in `.env.local`. Preserve the API configuration when pulling environment files, then restart/rebuild. Clerk creates its user profile during sign-up; both forms return directly to Home, with no onboarding. The signed-in header uses Clerk’s user menu and personalized greeting. Missing configuration shows an explicit setup notice.

## Experience

- **Home:** a personalized greeting and Add Footage open the device video picker. Selecting footage immediately replaces the greeting with the video and starts analysis in the background. The discreet change icon opens the same picker.
- **Continuous playback:** navigation never remounts or changes the active video source. Play/pause state, precise time, mute, and playback speed survive Home → Analysis → Library. Finishing an upload’s analysis switches to the API video while preserving playback position and play/pause state. The player uses the skater crop and its matching pose when `/app/view` is available, and falls back to the API’s per-move crop on older deployments. A single detected move opens cropped by default; selecting an element frame opens that move’s API crop. Crop pose overlays require coordinates returned for that crop.
- **Atmosphere:** real frames are sampled on load, during playback, and after seeking. The sampled RGB values color the surrounding haze. A blurred sampled image and feathered video bounds merge portrait or landscape footage into the page.
- **Analysis:** a thin tool rail reveals pose tracking, measured joint angles, AI feedback, and playback rates from ¼× to 2×. The timeline seeks at frame increments; previous/next-frame and thumbnail selection pause precisely. Play resumes from that point. API move timestamps select the frame previews shown below the player on Home and Analysis after analysis completes. Before results arrive, seven evenly spaced previews are decoded separately without seeking the visible player.
- **Feedback:** API scores, TES, points lost, move selection, base values, GOE, optional physics, coaching, and drills remain available. Practice checkboxes last for the current active analysis. Explicit segment, skater crop, rendered skeleton, and skeleton-only actions change the shared player’s presentation and preserve its absolute position when returning to full footage.
- **Library:** the backend’s saved footage appears as a simple thumbnail archive. Selecting a different clip makes it active; selecting the current analysis preserves its position. No session/element categories or simulated chat.

The API client handles immediate `200` results and processing `202` responses, polling with `retry_after_s` / `Retry-After`. Known analysis IDs persist locally so refresh can resume a job. Refresh before an upload returns its ID requires selecting it again. Changing the active analysis cancels old requests. Transient connection/server errors retry once and then expose a retry action. Results cache in memory during navigation; actual media/history persistence belongs to the backend.

The supplied API exposes shared history without user-scoped authentication or filtering. Clerk authenticates the frontend; private per-user archives require backend support. The PWA caches public images only, never HTML/RSC, authentication, API responses, or video range requests.

Legacy `/session?id=...` links redirect to Home with the selected analysis. `/analysis?id=...` also supports deep links. Practice now lives within analysis feedback; `/plan` remains an analysis alias.

## Verify

```bash
npm test
npm run lint
npm run build
```

Tests cover multipart options, immediate completion, processing and cancellation, backend and tunnel errors, move views, missing configuration, joint-angle math, and service-worker authentication/cache exclusions. Browser verification should also check one video element, unchanged paused time and continuous playing time across navigation, real upload completion showing the returned API video, thumbnails/frame stepping, alternate views, and mobile/desktop layouts.
