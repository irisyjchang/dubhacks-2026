import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createVoiceNotes, sendVoiceNote } from './voice-notes.mjs'

test('every new eligible reply creates audio; retries reuse upload across restarts', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'coach-voice-'))
  try {
    let requests = 0, uploads = 0
    const options = { directory, env: { ELEVENLABS_API_KEY: 'test', ELEVENLABS_MEMO_VOICE_ID: 'memo-voice', ELEVENLABS_CALL_VOICE_ID: 'call-voice', ELEVENLABS_VOICE_ID: 'shared-voice' }, encode: async data => data, fetchImpl: async (_url, request) => {
      requests++
      assert.equal(request.headers['xi-api-key'], 'test')
      assert.equal(_url, 'https://api.elevenlabs.io/v1/text-to-dialogue?output_format=mp3_44100_128')
      assert.deepEqual(JSON.parse(request.body), { inputs: [{ text: 'Keep a soft reach.', voice_id: 'memo-voice' }], model_id: 'eleven_v4' })
      return { ok: true, arrayBuffer: async () => new Uint8Array([1, 2]).buffer }
    } }
    const upload = async input => { uploads++; assert.equal(input.fileName, 'skate-coach.m4a'); return { attachment: { guid: 'audio-guid' } } }
    for (let choice = 0; choice < 5; choice++) {
      const prepare = createVoiceNotes(options)
      const result = await prepare(`reply-${choice}`, 'Keep a soft reach.', upload)
      assert.equal(result.type, 'audio')
    }
    assert.deepEqual(await createVoiceNotes(options)('reply-0', 'Keep a soft reach.', upload), { type: 'audio', guid: 'audio-guid' })
    assert.equal(requests, 5)
    assert.equal(uploads, 5)
  } finally { await rm(directory, { recursive: true, force: true }) }
})
test('missing key and speech failures persist text fallback', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'coach-voice-'))
  try {
    const unavailable = async () => { throw new Error('provider unavailable') }
    for (const [id, env] of [['missing', {}], ['failed', { ELEVENLABS_API_KEY: 'test' }]]) {
      const prepare = createVoiceNotes({ directory, env, fetchImpl: unavailable, warn: () => {} })
      assert.deepEqual(await prepare(id, 'Answer', unavailable), { type: 'text' })
    }
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test('native audio sends omit incompatible reply targets and preserve idempotency', async () => {
  const calls = []
  const remote = { messages: { sendAttachment: async (...args) => { calls.push(args); return { guid: 'sent' } } } }
  assert.deepEqual(await sendVoiceNote(remote, 'chat', 'audio', 'stable-key'), { guid: 'sent' })
  assert.deepEqual(calls, [['chat', 'audio', { clientMessageId: 'stable-key', isAudioMessage: true }]])
})


test('an explicit legacy model keeps the text-to-speech request contract', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'coach-voice-'))
  try {
    let requests = 0
    const prepare = createVoiceNotes({ directory,
      env: { ELEVENLABS_API_KEY: 'test', ELEVENLABS_MODEL_ID: 'eleven_multilingual_v2', ELEVENLABS_VOICE_ID: 'custom' },
      encode: async data => data,
      fetchImpl: async (url, request) => {
        requests++
        assert.equal(url, 'https://api.elevenlabs.io/v1/text-to-speech/custom?output_format=mp3_44100_128')
        assert.deepEqual(JSON.parse(request.body), { text: 'Answer', model_id: 'eleven_multilingual_v2' })
        return { ok: true, arrayBuffer: async () => new Uint8Array([1]).buffer }
      },
    })
    assert.deepEqual(await prepare('legacy', 'Answer', async () => ({ attachment: { guid: 'legacy-audio' } })), { type: 'audio', guid: 'legacy-audio' })
    assert.equal(requests, 1)
  } finally { await rm(directory, { recursive: true, force: true }) }
})
