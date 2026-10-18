import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { encodeVoiceAudio, voiceFfmpeg } from './voice-audio.mjs'

test('encodes playable M4A with duration and rejects invalid source audio', async () => {
  const { stdout } = await promisify(execFile)(await voiceFfmpeg(), [
    '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.5', '-f', 'mp3', 'pipe:1',
  ], { encoding: 'buffer', timeout: 10000 })
  const audio = await encodeVoiceAudio(stdout)
  assert.equal(Buffer.from(audio).subarray(4, 8).toString(), 'ftyp')
  assert.ok(audio.length > 1000)
  await assert.rejects(encodeVoiceAudio(new Uint8Array([1, 2, 3])))
})
