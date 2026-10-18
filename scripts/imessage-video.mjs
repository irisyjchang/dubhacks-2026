import { mkdir, readFile, writeFile, rename, readdir } from 'node:fs/promises'
import { join, basename, extname } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { smsText } from './training-coach.mjs'

const MAX_BYTES = 199 * 1024 * 1024
const extensions = new Set(['.mov', '.mp4', '.m4v', '.webm', '.avi'])
export function videoAttachments(attachments) {
  return attachments.filter(file => !file.isHidden && !file.isSticker &&
    (file.mimeType?.startsWith('video/') || extensions.has(extname(file.fileName || '').toLowerCase())))
}

// Durable local receipts link Photon events to existing Python upload jobs.
export function createIncomingVideoHandler({ student, agentId, authorize, memory, muted, download, send, upload,
  mode = process.env.IMESSAGE_VIDEO_MODE || 'nvidia', apiKey = process.env.NVIDIA_API_KEY,
  fetchImpl = fetch, sleep = delay, pollMs = 2000,
  directory = join(process.cwd(), '.coach', 'imessage-videos'), endpoint = 'http://127.0.0.1:8001',
  onError = () => console.error('iMessage video task pending; will resume on reconnect.') }) {
  const active = new Map()
  const read = async response => {
    if (!response.ok) throw new Error('Video service unavailable')
    return response.json()
  }
  const permitted = async message => {
    if (message.space.kind !== 'group' && message.sentBy.handle !== student) return false
    await authorize(message.space.id, message.sentBy.handle)
    return !(await memory.get()).paused && !(message.space.kind === 'group' && await muted(message.space.id))
  }
  async function save(state) {
    await mkdir(directory, { recursive: true, mode: 0o700 })
    const path = join(directory, `${state.message.id}.json`)
    await writeFile(`${path}.tmp`, JSON.stringify(state), { mode: 0o600 })
    await rename(`${path}.tmp`, path)
  }
  async function reply(state, text, suffix, voiceEligible = false) {
    if (!await permitted(state.message)) return false
    const result = await send({ senderId: agentId, spaceId: state.message.space.id,
      replyTo: state.message.nativeMessageId, voiceEligible, content: { type: 'text', text } },
    `dh26-video-${state.message.id}-${suffix}`)
    if (result.status === 'failed') throw new Error('Video reply delivery failed')
    return true
  }
  async function run(state) {
    if (state.done || !await permitted(state.message)) return
    // Keep pending jobs tied to their original service across upgrades.
    const service = state.endpoint || (state.jobId ? 'http://127.0.0.1:8000' : endpoint)
    if (!state.jobId) {
      await reply(state, 'Video received. I’ll send back an annotated MOV and save the report so you can ask follow-up questions. Clips must be 30 seconds or less.', 'received')
      const chunks = []
      let size = 0
      for await (const chunk of download(state.attachment.guid)) {
        if (chunk.type !== 'primaryChunk') continue
        const data = chunk.data
        size += data.length
        if (size > MAX_BYTES) throw new Error('Video is too large')
        chunks.push(data)
      }
      if (!size) throw new Error('Video download is empty')
      const form = new FormData()
      form.set('video', new Blob(chunks), state.fileName)
      form.set('mode', mode)
      if (mode === 'nvidia' && apiKey) form.set('api_key', apiKey)
      const job = await read(await fetchImpl(`${service}/api/jobs`, { method: 'POST', body: form,
        headers: { 'Idempotency-Key': state.message.id }, signal: AbortSignal.timeout(60000) }))
      if (!/^[a-f0-9]{32}$/.test(job.id)) throw new Error('Invalid video job')
      state.jobId = job.id
      state.endpoint = service
      await save(state)
    }
    for (let attempt = 0; attempt < 600; attempt++) {
      const response = await fetchImpl(`${service}/api/jobs/${state.jobId}`, { signal: AbortSignal.timeout(15000) })
      if (response.status === 404) {
        await reply(state, 'The video service restarted before this upload finished. Please send the clip again.', 'expired')
        state.done = true; await save(state); return
      }
      const job = await read(response)
      if (job.status === 'failed') {
        await reply(state, 'This clip could not be analyzed. Please send a readable MOV or MP4 of 30 seconds or less, or try the web upload for details.', 'failed')
        state.done = true; await save(state); return
      }
      if (job.status === 'completed') {
        if (job.feedback_sync !== 'saved') {
          await read(await fetchImpl(`${service}/api/jobs/${state.jobId}/coach`, { method: 'POST', signal: AbortSignal.timeout(15000) }))
          await sleep(pollMs); continue
        }
        if (!await permitted(state.message)) return
        if (!state.videoGuid) {
          if (!upload) throw new Error('Video upload transport unavailable')
          const video = await fetchImpl(`${service}/api/jobs/${state.jobId}/files/feedback.mov`, { signal: AbortSignal.timeout(60000) })
          if (!video.ok) throw new Error('Annotated MOV is unavailable')
          const chunks = []
          let bytes = 0
          for await (const chunk of video.body) {
            bytes += chunk.length
            if (bytes > MAX_BYTES) throw new Error('Annotated MOV exceeds the iMessage size limit')
            chunks.push(chunk)
          }
          if (!bytes) throw new Error('Annotated MOV is empty')
          if (!await permitted(state.message)) return
          const result = await upload({ data: new Uint8Array(Buffer.concat(chunks)), fileName: 'feedback.mov' })
          if (!result.attachment?.guid) throw new Error('Annotated MOV upload failed')
          state.videoGuid = result.attachment.guid
          await save(state)
        }
        if (!state.videoSent) {
          if (!await permitted(state.message)) return
          const result = await send({ senderId: agentId, spaceId: state.message.space.id,
            replyTo: state.message.nativeMessageId, content: { type: 'attachment', guid: state.videoGuid } },
          `dh26-video-${state.message.id}-mov`)
          if (result.status === 'failed') throw new Error('MOV delivery failed')
          state.videoSent = true
          await save(state)
        }
        const text = smsText(`Here’s the annotated video for ${state.fileName}. Its backend report is saved—ask me a follow-up about this clip.\n${job.warning || ''}\n${job.report || 'Your report is ready.'}`)
        if (await reply(state, text, 'completed')) { state.done = true; await save(state) }
        return
      }
      await sleep(pollMs)
    }
    await reply(state, 'Your video is still queued. The report will appear in your timeline when analysis completes.', 'waiting')
  }
  function launch(state) {
    if (active.has(state.message.id)) return
    // Bound parallel downloads; Python already serializes analysis.
    if (active.size >= 2) return
    const task = run(state).catch(async error => {
      onError(error)
      await reply(state, 'Video analysis or delivery is pending. The backend will retry automatically. If it stays pending, check npm run imessage-video-server and the configured NVIDIA key.', 'pending').catch(() => {})
    }).finally(() => active.delete(state.message.id))
    active.set(state.message.id, task)
  }
  return {
    async handle(message, attachments) {
      const videos = videoAttachments(attachments)
      if (!videos.length) return false
      if (!await permitted(message)) return true
      await mkdir(directory, { recursive: true, mode: 0o700 })
      const path = join(directory, `${message.id}.json`)
      let state
      try { state = JSON.parse(await readFile(path, 'utf8')) }
      catch (error) { if (error.code !== 'ENOENT') throw error }
      if (!state) {
        const file = videos[0]
        const fileName = basename((file.fileName || 'skating.mp4').replaceAll('\\', '/')).slice(0, 150)
        state = { message, attachment: { guid: file.guid }, fileName }
        if (videos.length > 1 || file.totalBytes > MAX_BYTES || !extensions.has(extname(fileName).toLowerCase())) {
          await reply(state, 'Please send one MOV, MP4, M4V, WebM, or AVI clip at a time, under 199 MB and 30 seconds.', 'invalid')
          state.done = true
        }
        await save(state)
      }
      launch(state)
      return true
    },
    async resume() {
      await mkdir(directory, { recursive: true, mode: 0o700 })
      for (const name of await readdir(directory)) {
        if (!/^sp-[a-f0-9]{64}\.json$/.test(name)) continue
        const state = JSON.parse(await readFile(join(directory, name), 'utf8'))
        if (!state.done) launch(state)
      }
    },
    async drain() { await Promise.all(active.values()) },
  }
}
