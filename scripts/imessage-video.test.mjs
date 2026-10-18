import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createIncomingVideoHandler } from './imessage-video.mjs'
const message = { id: `sp-${'a'.repeat(64)}`, nativeMessageId: 'photon-guid',
  sentBy: { handle: 'owner' }, space: { id: 'chat', kind: 'direct' } }
const attachment = { guid: 'video-guid', fileName: 'spin.mov', mimeType: 'video/quicktime', totalBytes: 4 }
const jobId = 'b'.repeat(32)
const json = data => ({ ok: true, status: 200, json: async () => data })

test('iMessage video returns the backend MOV, saves follow-up context, and deduplicates after restart', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'imsg-video-'))
  try {
    const sent = [], calls = []
    let downloaded = 0, synced = false
    const options = { directory, student: 'owner', agentId: 'agent', mode: 'nvidia', apiKey: 'test-key',
      authorize: async () => {}, memory: { get: async () => ({ paused: false }) }, muted: async () => false,
      download: async function* () { downloaded++; yield { type: 'primaryChunk', data: new Uint8Array([1,2,3,4]) } },
      send: async (body, key) => { sent.push({ body, key }); return { status: 'submitted' } }, sleep: async () => {},
      upload: async input => {
        assert.equal(synced, true, 'report must reach persistent coach memory before returning the video')
        assert.equal(input.fileName, 'feedback.mov')
        assert.deepEqual([...input.data], [7,8,9])
        return { attachment: { guid: 'annotated-mov-guid' } }
      },
      fetchImpl: async (url, request) => {
        calls.push(url)
        if (url.endsWith('/api/jobs')) {
          assert.equal(request.body.get('mode'), 'nvidia')
          assert.equal(request.body.get('api_key'), 'test-key')
          assert.equal(request.headers['Idempotency-Key'], message.id)
          return json({ id: jobId })
        }
        if (url.endsWith('/coach')) { synced = true; return json({ feedback_sync: 'saved' }) }
        if (url.endsWith('/feedback.mov')) return { ok: true, body: (async function* () { yield new Uint8Array([7,8,9]) })() }
        return json({ status: 'completed', feedback_sync: synced ? 'saved' : 'failed', report: 'At 2s, review arm reach.' })
      } }
    const handler = createIncomingVideoHandler(options)
    assert.equal(await handler.handle(message, [attachment]), true)
    await handler.drain()
    assert.equal(downloaded, 1)
    assert.equal(sent.length, 3)
    assert.deepEqual(sent[1].body.content, { type: 'attachment', guid: 'annotated-mov-guid' })
    assert.equal(sent[1].body.replyTo, message.nativeMessageId)
    assert.equal(sent[2].body.voiceEligible, false)
    assert.match(sent[2].body.content.text, /backend report is saved/)
    assert.match(sent[2].body.content.text, /At 2s/)
    assert.ok(calls.some(url => url.endsWith('/coach')))
    const restart = createIncomingVideoHandler(options)
    await restart.handle(message, [attachment]); await restart.drain()
    assert.equal(sent.length, 3)
    assert.equal(downloaded, 1)
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test('MOV retries reuse the persisted attachment and stable send key after a connection failure', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'imsg-video-'))
  let uploads = 0, renders = 0, fail = true
  const videos = []
  const options = { directory, student: 'owner', agentId: 'agent',
    authorize: async () => {}, memory: { get: async () => ({}) }, sleep: async () => {}, onError: () => {},
    download: async function* () { yield { type: 'primaryChunk', data: new Uint8Array([1]) } },
    upload: async () => { uploads++; return { attachment: { guid: 'saved-video' } } },
    send: async (body, key) => {
      if (body.content.type === 'attachment') {
        videos.push({ body, key })
        if (fail) { fail = false; throw new Error('connection dropped') }
      }
      return { status: 'submitted' }
    },
    fetchImpl: async url => {
      if (url.endsWith('/api/jobs')) { renders++; return json({ id: jobId }) }
      if (url.endsWith('/feedback.mov')) return { ok: true, body: (async function* () { yield new Uint8Array([2]) })() }
      return json({ status: 'completed', feedback_sync: 'saved', report: 'Backend feedback.' })
    } }
  try {
    let handler = createIncomingVideoHandler(options)
    await handler.handle(message, [attachment]); await handler.drain()
    handler = createIncomingVideoHandler(options)
    await handler.resume(); await handler.drain()
    assert.equal(uploads, 1)
    assert.equal(renders, 1)
    assert.equal(videos.length, 2)
    assert.deepEqual(videos[0], videos[1])
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test('STOP while analysis runs prevents uploading or returning the generated MOV', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'imsg-video-'))
  let paused = false
  const sent = []
  try {
    const handler = createIncomingVideoHandler({ directory, student: 'owner', agentId: 'agent',
      authorize: async () => {}, memory: { get: async () => ({ paused }) }, sleep: async () => {},
      download: async function* () { yield { type: 'primaryChunk', data: new Uint8Array([1]) } },
      send: async body => { sent.push(body); return { status: 'submitted' } },
      upload: async () => assert.fail('paused video must not be uploaded'),
      fetchImpl: async url => {
        if (url.endsWith('/api/jobs')) return json({ id: jobId })
        paused = true
        return json({ status: 'completed', feedback_sync: 'saved', report: 'Feedback' })
      } })
    await handler.handle(message, [attachment]); await handler.drain()
    assert.equal(sent.length, 1, 'only the initial receipt precedes STOP')
  } finally { await rm(directory, { recursive: true, force: true }) }
})
test('other people, muted groups, and paused DMs cannot add videos to owner progress', async () => {
  const unexpected = async () => assert.fail('unexpected processing')
  const options = { student: 'owner', authorize: async () => {}, memory: { get: async () => ({ paused: true }) },
    muted: async () => true, download: unexpected, send: unexpected, fetchImpl: unexpected }
  const handler = createIncomingVideoHandler(options)
  assert.equal(await handler.handle({ ...message, sentBy: { handle: 'other' } }, [attachment]), true)
  assert.equal(await handler.handle(message, [attachment]), true)
  assert.equal(await createIncomingVideoHandler({ ...options, memory: { get: async () => ({}) } }).handle(
    { ...message, space: { id: 'chat', kind: 'group' } }, [attachment]), true)
})
test('multiple videos and oversized videos get actionable rejection without downloads', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'imsg-video-'))
  try {
    const sent = []
    const handler = createIncomingVideoHandler({ directory, student: 'owner', authorize: async () => {},
      memory: { get: async () => ({}) }, send: async body => { sent.push(body); return {} },
      download: async () => assert.fail('must not download') })
    await handler.handle(message, [attachment, attachment]); await handler.drain()
    await handler.handle({ ...message, id: `sp-${'c'.repeat(64)}` }, [{ ...attachment, totalBytes: 200 * 1024 * 1024 }]); await handler.drain()
    assert.equal(sent.length, 2)
    assert.ok(sent.every(body => body.content.text.includes('one MOV')))
  } finally { await rm(directory, { recursive: true, force: true }) }
})
