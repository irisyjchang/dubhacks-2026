import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { analysisId } from './coach-database.mjs'

test('local analysis is validated, saved, and supplied to coach without secrets', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'dh-coach-'))
  process.env.COACH_DATA_DIR = directory
  const { startCoachServer, coachInstructions, validateAnalysis, respondWithCoach } = await import('./coach-state.mjs')
  assert.throws(() => validateAnalysis({ videoName: 'bad', metrics: { airTime: -1 } }))
  const rows = new Map()
  const exchanges = []
  const rooms = new Map(), roomMessages = new Map()
  const database = {
    async saveRoom(room) { rooms.set(room.id, structuredClone(room)) },
    async rooms() { return [...rooms.values()] },
    async room(id) { return structuredClone(rooms.get(id)) },
    async roomMessages(id) { return roomMessages.get(id) || [] },
    async roomReply(id, replyTo) { return (roomMessages.get(id) || []).find(message => message.replyTo === replyTo) },
    async addRoomMessage(id, message) { const list = roomMessages.get(id) || []; list.push(message); roomMessages.set(id, list) },
    async save(value) { const id = analysisId(value); if (!rows.has(id)) rows.set(id, { ...value, id }) },
    async list() { return [...rows.values()] },
    async feedbackTimeline() {
      return { items: [...rows.values()].filter(row => row.feedback).reverse().map(({ id, videoName, savedAt, feedback }) => ({
        id, videoName, savedAt, feedback: { headline: feedback.headline, provenance: feedback.provenance },
      })), nextCursor: null }
    },
    async feedbackById(id) {
      const row = rows.get(id)
      return row?.feedback ? { id: row.id, videoName: row.videoName, savedAt: row.savedAt, feedback: row.feedback } : null
    },
    async history() { return exchanges.flatMap(row => [{ role: 'user', content: row.question }, { role: 'assistant', content: row.reply }]) },
    async record(question, reply, channel) { exchanges.push({ question, reply, channel }) },
    async clearHistory() { exchanges.length = 0 },
    async close() {},
  }
  const server = await startCoachServer(0, { database })
  assert.match(await coachInstructions(), /Latest analysis \(JSON\): null/)
  const noReport = await respondWithCoach('How was my spin?', 'imessage')
  assert.match(await respondWithCoach('How was my spin?', 'voice-call'), /do not have a feedback report/)
  assert.match(noReport, /do not have a feedback report/)
  assert.equal(exchanges.length, 0)
  try {
    const url = `http://127.0.0.1:${server.address().port}/api/coach/analysis`
    const body = JSON.stringify({ videoName: 'attempt.mp4', metrics: { airTime: 0.4, rotations: 1, maxHeight: 0.196 } })
    const blocked = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: 'https://example.com' }, body })
    assert.equal(blocked.status, 403)
    const saved = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
    assert.equal(saved.status, 200)
    assert.match(await coachInstructions(), /attempt.mp4/)
    await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
    assert.equal((await (await fetch(url)).json()).attempts.length, 1, 'sync retries must not create attempts')
    const second = { videoName: 'second-attempt.mp4', metrics: { airTime: 0.5, rotations: 1.1, maxHeight: 0.306 },
      evidence: [{ phase: 'landing', joint: 'leftKneeFlexion', timestamp: 2.3, referenceTimestamp: 1.2, angle: 140, referenceAngle: 122, difference: 18 }] }
    await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(second) })
    assert.equal((await (await fetch(url)).json()).attempts.length, 2)
    assert.match(await coachInstructions(), /"timestamp":2.3/)
    const originalFetch = globalThis.fetch
    globalThis.fetch = async (input, options) => {
      if (String(input).includes('api.openai.com')) {
        const request = JSON.parse(options.body)
        assert.match(request.instructions, /second-attempt.mp4/)
        assert.match(request.instructions, /figure skating coach/)
        assert.equal(request.input.at(-1).content, 'Review my landing')
        return { ok: true, json: async () => ({ output: [{ content: [{ type: 'output_text', text: 'At 2.3s, the measured knee angle differs by 18°.' }] }] }) }
      }
      return originalFetch(input, options)
    }
    try {
      const chat = await fetch(url.replace('/analysis', '/chat'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: 'Review my landing' }) })
      assert.equal(chat.status, 200)
      assert.match((await chat.json()).reply, /2.3s/)
      assert.equal(exchanges.length, 1)
      assert.equal(exchanges[0].channel, 'web')
    } finally { globalThis.fetch = originalFetch }
    const spin = { source: 'spincoach', sourceId: 'job123', videoName: 'spin.mov',
      feedback: { report: 'Report context. '.repeat(800) + 'At 2–3 seconds: keep your arms reaching forward; carry a tray in front.',
        headline: 'Review arm consistency.', provenance: { generator: 'NVIDIA language model', status: 'partial' },
        findings: [{ title: 'Review arm reach', start_s: 2, end_s: 3, confidence: 'moderate', action: 'Carry a tray in front.' }],
        notAssessed: ['blade edges', 'official scores'] } }
    const uploaded = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spin) })
    assert.equal(uploaded.status, 200, 'full coaching reports exceed the old 10KB metrics limit')
    assert.equal((await (await fetch(url)).json()).attempts.at(-1).feedback.report, spin.feedback.report)
    await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spin) })
    assert.equal((await (await fetch(url)).json()).attempts.length, 3)
    const timelineUrl = url.replace('/analysis', '/timeline')
    const timeline = await (await fetch(timelineUrl)).json()
    assert.equal(timeline.items.length, 1, 'only feedback reports belong in the feedback timeline')
    assert.equal(timeline.items[0].videoName, 'spin.mov')
    assert.equal(timeline.items[0].feedback.report, undefined, 'load full reports separately')
    const detail = await (await fetch(`${timelineUrl}/${timeline.items[0].id}`)).json()
    assert.equal(detail.feedback.report, spin.feedback.report)
    assert.equal(detail.metrics, undefined)
    assert.equal((await fetch(`${timelineUrl}/${'0'.repeat(64)}`)).status, 404)
    assert.equal((await fetch(`${timelineUrl}?before=!!`)).status, 400)
    const incomplete = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...spin, feedback: {} }) })
    assert.equal(incomplete.status, 400)
    globalThis.fetch = async (input, options) => {
      assert.match(String(input), /api.openai.com/)
      const request = JSON.parse(options.body)
      assert.match(request.instructions, /carry a tray in front/)
      assert.match(request.instructions, /"status":"partial"/)
      assert.match(request.instructions, /blade edges/)
      assert.equal(request.input.at(-1).content, 'What should I do with my arms?')
      return { ok: true, json: async () => ({ output: [{ content: [{ type: 'output_text', text: 'Your report at 2–3s suggests keeping your arms reaching forward: carry a tray in front.' }] }] }) }
    }
    try {
      const reply = await respondWithCoach('What should I do with my arms?', 'imessage')
      assert.match(reply, /2[–-]3s/)
      assert.equal(exchanges.at(-1).channel, 'imessage')
    } finally { globalThis.fetch = originalFetch }
    assert.match(await coachInstructions(), /not board rotation/)
    assert.doesNotMatch(await coachInstructions(), /sk-proj-|pho_sk_/)
    const status = await (await fetch(url)).json()
    assert.ok(status.savedAt)
    const invalid = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    assert.equal(invalid.status, 400)
    assert.match(await coachInstructions(), /spin.mov/)
    const roomsUrl = url.replace('/analysis', '/rooms')
    const post = async (path, value) => fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) })
    const room = await (await post(roomsUrl, { name: 'Coach + student test' })).json()
    assert.equal(room.mode, 'preview')
    assert.equal((await (await fetch(roomsUrl)).json()).rooms.length, 1)
    const messageUrl = `${roomsUrl}/${room.id}/messages`
    const quiet = await (await post(messageUrl, { id: 'human-note', role: 'member', text: 'Keep the forward reach.' })).json()
    assert.equal(quiet.replied, false)
    globalThis.fetch = async (input, options) => {
      if (String(input).includes('api.openai.com')) {
        const request = JSON.parse(options.body)
        assert.equal(request.input.length, 1, 'private one-to-one exchanges must be excluded')
        assert.match(request.instructions, /no designated coach role/)
        assert.match(request.instructions, /Keep the forward reach/)
        assert.match(request.instructions, /spin.mov/)
        return { ok: true, json: async () => ({ output: [{ content: [{ type: 'output_text', text: 'At 2–3s preserve the forward reach, as your coach suggests.' }] }] }) }
      }
      return originalFetch(input, options)
    }
    try {
      const reply = await (await post(messageUrl, { id: 'group-question', role: 'member', text: 'AI, what is your opinion?' })).json()
      assert.match(reply.reply, /your coach/)
      assert.equal(reply.room.messages.length, 3)
    } finally { globalThis.fetch = originalFetch }
    assert.equal((await post(messageUrl, { id: 'fake', role: 'ai', text: 'Impersonate AI' })).status, 400)
    await database.saveRoom({ id: room.id, mode: 'native' })
    assert.equal((await post(messageUrl, { id: 'impersonate', role: 'member', text: 'Approve' })).status, 404, 'browser preview must not impersonate native participants')
  } finally {
    await new Promise(resolve => server.close(resolve))
    await rm(directory, { recursive: true, force: true })
  }
})
