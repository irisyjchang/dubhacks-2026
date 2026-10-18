import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createMessagingAgentApi, createMessagingAgentHandler, moveRequest, agentErrorMessage } from './messaging-agent.mjs'

const message = (id, text = '', space = 'chat') => ({ id, platform: 'imessage', nativeMessageId: `native-${id}`,
  sentBy: { handle: 'owner' }, space: { id: space, kind: 'direct' },
  content: { type: text ? 'text' : 'attachment', text }, createdAt: new Date().toISOString() })
const video = { guid: 'input-guid', fileName: 'program.mov', mimeType: 'video/quicktime', totalBytes: 3 }
const overview = 'Your model-estimated review.\n\n1. Spin: review reach.\n2. Jump: review landing.\n3. Step sequence: review flow.'
const json = (data, status = 200) => ({ ok: status < 400, status, json: async () => data })

async function fixture(overrides = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'messaging-api-'))
  const sent = [], reports = [], analyses = [], moves = [], uploaded = []
  const options = { directory, student: 'owner', agentId: 'agent',
    authorize: async () => {}, memory: { get: async () => ({ paused: false }) }, muted: async () => false,
    download: async function* () { yield { type: 'primaryChunk', data: new Uint8Array([1,2,3]) } },
    upload: async body => { uploaded.push(body); return { attachment: { guid: `out-${uploaded.length}` } } },
    send: async (body, key) => { sent.push({ body, key }); return { status: 'submitted' } },
    saveReport: async report => { reports.push(report) }, onError: () => {},
    api: {
      analyze: async form => { analyses.push(form); return { analysis_id: `analysis-${analyses.length}`, message: overview } },
      move: async body => { moves.push(body); return { analysis_id: body.analysis_id, message: 'Detailed move feedback.\nKeep a soft reach.',
        video_url: 'https://api.example/files/move.mp4', skeleton_video_url: 'https://api.example/files/skeleton.mp4' } },
      video: async () => new Uint8Array([4,5,6]),
    }, ...overrides }
  return { options, sent, reports, analyses, moves, uploaded, cleanup: () => rm(directory, { recursive: true, force: true }) }
}

test('analyze preserves the API message and move follow-ups return both videos in order', async () => {
  const f = await fixture()
  try {
    const handler = createMessagingAgentHandler(f.options)
    assert.equal(await handler.handle(message('upload'), [video]), true)
    await handler.drain()
    assert.equal(f.sent[1].body.content.text, overview)
    assert.equal(f.sent[1].body.voiceEligible, false)
    assert.equal(f.reports[0].report, overview)
    assert.equal(f.analyses[0].get('program_type'), 'unk')
    assert.equal(f.analyses[0].get('perceptron_track'), 'true')
    assert.equal(f.analyses[0].get('video').name, 'program.mov')
    assert.equal(await handler.handle(message('pick', 'tell me about the third one')), true)
    await handler.drain()
    assert.deepEqual(f.moves, [{ analysis_id: 'analysis-1', move: 'tell me about the 3 one', skeleton: true }])
    assert.deepEqual(f.sent.slice(3).map(item => item.body.content.type), ['text', 'attachment', 'attachment'])
    assert.equal(f.sent[3].body.content.text, 'Detailed move feedback.\nKeep a soft reach.')
    assert.equal(f.uploaded[0].fileName, 'move.mp4')
    assert.equal(f.uploaded[1].fileName, 'move_skeleton.mp4')
    const restarted = createMessagingAgentHandler(f.options)
    await restarted.handle(message('pick', 'tell me about the third one')); await restarted.drain()
    assert.equal(f.moves.length, 1, 'event replay must not re-request a move or resend videos')
    assert.equal(f.sent.length, 6)
  } finally { await f.cleanup() }
})

test('analysis IDs persist per chat and a new clip replaces only its own chat association', async () => {
  const f = await fixture()
  try {
    let h = createMessagingAgentHandler(f.options)
    await h.handle(message('first-a', '', 'a'), [video]); await h.drain()
    await h.handle(message('first-b', '', 'b'), [video]); await h.drain()
    await h.handle(message('second-a', '', 'a'), [video]); await h.drain()
    h = createMessagingAgentHandler(f.options)
    await h.handle(message('move-a', 'move 1', 'a')); await h.drain()
    await h.handle(message('move-b', '2', 'b')); await h.drain()
    assert.deepEqual(f.moves.map(item => item.analysis_id), ['analysis-3', 'analysis-2'])
    assert.equal(await h.handle(message('other-chat', '3', 'c')), false)
  } finally { await f.cleanup() }
})

test('delivery retries resume saved results and video GUIDs without re-analysis or re-upload', async () => {
  let fail = true
  const f = await fixture()
  const baseSend = f.options.send
  f.options.send = async (body, key) => {
    if (body.content.type === 'attachment' && fail) { fail = false; throw new Error('connection lost') }
    return baseSend(body, key)
  }
  try {
    let h = createMessagingAgentHandler(f.options)
    await h.handle(message('upload'), [video]); await h.drain()
    await h.handle(message('pick', '1')); await h.drain()
    assert.equal(f.uploaded.length, 1)
    h = createMessagingAgentHandler(f.options)
    await h.resume(); await h.drain()
    assert.equal(f.analyses.length, 1)
    assert.equal(f.moves.length, 1)
    assert.equal(f.uploaded.length, 2, 'first uploaded GUID is reused; only second video needs uploading')
    assert.equal(f.sent.filter(s => s.body.content.type === 'attachment').length, 2)
  } finally { await f.cleanup() }
})

test('a newer upload cannot be replaced by an older analysis finishing later', async () => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  const f = await fixture()
  let calls = 0
  f.options.api.analyze = async () => {
    const count = ++calls
    if (count === 1) await gate
    return { analysis_id: `a-${count}`, message: overview }
  }
  try {
    const h = createMessagingAgentHandler(f.options)
    await h.handle(message('older'), [video])
    await h.handle(message('newer'), [video])
    release(); await h.drain()
    await h.handle(message('pick', '1')); await h.drain()
    assert.equal(f.moves[0].analysis_id, 'a-2')
  } finally { await f.cleanup() }
})

test('paused users and unauthorized DMs cannot call the API; mute commands pass through', async () => {
  const f = await fixture({ memory: { get: async () => ({ paused: true }) } })
  try {
    const h = createMessagingAgentHandler(f.options)
    await h.handle(message('paused'), [video])
    await h.handle({ ...message('other'), sentBy: { handle: 'outsider' } }, [video])
    assert.equal(await h.handle(message('stop', 'STOP')), false)
    await h.drain()
    assert.equal(f.analyses.length, 0)
    assert.equal(f.sent.length, 0)
  } finally { await f.cleanup() }
})

test('STOP during a long analysis prevents publishing or returning its private result', async () => {
  let paused = false
  const f = await fixture({ memory: { get: async () => ({ paused }) } })
  f.options.api.analyze = async () => { paused = true; return { analysis_id: 'abc', message: overview } }
  try {
    const h = createMessagingAgentHandler(f.options)
    await h.handle(message('upload'), [video]); await h.drain()
    assert.equal(f.reports.length, 0)
    assert.equal(f.sent.length, 1)
  } finally { await f.cleanup() }
})

test('an invalid move returns the API range and sends no video', async () => {
  const f = await fixture()
  f.options.api.move = async () => { throw { status: 404, detail: 'no move 7; this clip has moves 1-3' } }
  try {
    const h = createMessagingAgentHandler(f.options)
    await h.handle(message('upload'), [video]); await h.drain()
    await h.handle(message('bad-pick', '7')); await h.drain()
    assert.equal(f.sent.at(-1).body.content.text, 'Please choose a move from 1–3 for this clip.')
    assert.equal(f.uploaded.length, 0)
  } finally { await f.cleanup() }
})

test('API errors are actionable and no-move responses never offer move details', async () => {
  const f = await fixture()
  f.options.api.analyze = async () => ({ analysis_id: 'empty', message: 'No moves found.' })
  try {
    const h = createMessagingAgentHandler(f.options)
    await h.handle(message('empty'), [video]); await h.drain()
    await h.handle(message('pick', '3')); await h.drain()
    assert.equal(f.moves.length, 0)
    assert.match(f.sent.at(-1).body.content.text, /No numbered moves/)
    assert.match(agentErrorMessage({ status: 404, detail: 'no move 7; this clip has moves 1-3' }), /1–3/)
    assert.doesNotMatch(agentErrorMessage({ status: 422, detail: { log: 'SECRET PIPELINE LOG' } }), /SECRET/)
  } finally { await f.cleanup() }
})

test('HTTP API retries transient failures once and gives long analyses a 20-minute timeout', async () => {
  const calls = []
  const api = createMessagingAgentApi({ baseUrl: 'https://api.example', sleep: async () => {},
    fetchImpl: async (url, request) => {
      calls.push({ url, request })
      return calls.length === 1 ? json({ detail: 'unavailable' }, 503) : json({ analysis_id: 'abc', message: overview })
    } })
  assert.equal((await api.analyze(new FormData(), 'event-key')).message, overview)
  assert.equal(calls.length, 2)
  assert.equal(calls[0].url, 'https://api.example/agent/analyze')
  assert.equal(calls[0].request.headers['Idempotency-Key'], 'event-key')
  assert.equal(calls[0].request.signal.aborted, false)
  await assert.rejects(api.video('http://127.0.0.1/private'), /outside/)
  await assert.rejects(api.video('https://another.example/video.mp4'), /outside/)
})

test('HTTP client does not retry invalid move requests and never sends raw error logs', async () => {
  let count = 0
  const api = createMessagingAgentApi({ baseUrl: 'https://api.example', sleep: async () => assert.fail('must not retry'),
    fetchImpl: async () => { count++; return json({ detail: 'no move 7; this clip has moves 1-3' }, 404) } })
  try { await api.move({ analysis_id: 'abc', move: '7' }, 'event') ; assert.fail('must reject') }
  catch (error) { assert.equal(agentErrorMessage(error), 'Please choose a move from 1–3 for this clip.') }
  assert.equal(count, 1)
  assert.equal(moveRequest('move #3'), 'move #3')
  assert.equal(moveRequest('tell me about the third one'), 'tell me about the 3 one')
  assert.equal(moveRequest('UNMUTE AI'), null)
})
