import { encodeVoiceAudio } from './voice-audio.mjs'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises'
import { join } from 'node:path'

export function createVoiceNotes({ env = process.env, fetchImpl = fetch, encode = encodeVoiceAudio,
  directory = join(process.cwd(), '.coach', 'voice-notes'), warn = () => console.warn('Voice generation unavailable; using text.') } = {}) {
  return async function prepare(key, text, upload) {
    // Persist the delivery format and upload GUID before attempting delivery.
    const id = createHash('sha256').update(key).digest('hex')
    const path = join(directory, `${id}.json`)
    await mkdir(directory, { recursive: true, mode: 0o700 })
    try { return JSON.parse(await readFile(path, 'utf8')) }
    catch (error) { if (error.code !== 'ENOENT') throw error }
    let result = { type: 'text' }
    if (env.ELEVENLABS_API_KEY) {
      try {
        const voice = env.ELEVENLABS_VOICE_ID || 'JBFqnCBsd6RMkjVDRZzb'
        const response = await fetchImpl(`https://api.elevenlabs.io/v1/text-to-speech/${encodeURIComponent(voice)}?output_format=mp3_44100_128`, {
          method: 'POST', signal: AbortSignal.timeout(30000),
          headers: { 'xi-api-key': env.ELEVENLABS_API_KEY, 'Content-Type': 'application/json', Accept: 'audio/mpeg' },
          body: JSON.stringify({ text, model_id: env.ELEVENLABS_MODEL_ID || 'eleven_multilingual_v2' }),
        })
        if (!response.ok) throw new Error('Speech request failed')
        const data = new Uint8Array(await response.arrayBuffer())
        if (!data.length || data.length > 10 * 1024 * 1024) throw new Error('Invalid audio size')
        const audio = await encode(data)
        const uploaded = await upload({ data: audio, fileName: 'skate-coach.m4a' })
        if (!uploaded.attachment?.guid) throw new Error('Audio upload failed')
        result = { type: 'audio', guid: uploaded.attachment.guid }
      } catch { warn() }
    }
    await writeFile(`${path}.tmp`, JSON.stringify(result), { mode: 0o600 })
    await rename(`${path}.tmp`, path)
    return result
  }
}

// Photon IMAgentKit rejects audio-message mode combined with replyTo.
export function sendVoiceNote(remote, chatId, guid, clientMessageId) {
  return remote.messages.sendAttachment(chatId, guid, { clientMessageId, isAudioMessage: true })
}
