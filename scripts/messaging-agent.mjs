import { mkdir, readFile, writeFile, rename, readdir } from 'node:fs/promises'
import { join, basename, extname } from 'node:path'
import { createHash } from 'node:crypto'
import { setTimeout as delay } from 'node:timers/promises'

const MAX_BYTES = 199 * 1024 * 1024
const VIDEO_EXTENSIONS = new Set(['.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm'])
const hash = value => createHash('sha256').update(value).digest('hex')
const ordinals = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth', 'thirteenth', 'fourteenth', 'fifteenth', 'sixteenth', 'seventeenth', 'eighteenth', 'nineteenth', 'twentieth']

export function moveRequest(text) {
  if (/^\/?(?:stop|start|mute(?: ai)?|unmute(?: ai)?|help|cancel|quit|unsubscribe)$/i.test(text.trim())) return null
  if (/\d/.test(text)) return text
  const ordinal = new RegExp(`\\b(${ordinals.join('|')})\\b`, 'i').exec(text)
  return ordinal ? text.replace(ordinal[0], String(ordinals.indexOf(ordinal[0].toLowerCase()) + 1)) : null
}

class AgentApiError extends Error {
  constructor(status, detail) {
    super('Skate Coach API request failed')
    this.status = status
    this.retryable = !status || status >= 500
    this.detail = detail
  }
}

export function agentErrorMessage(error) {
  if (error.status === 404) {
    const range = typeof error.detail === 'string' && /moves?\s+(\d+)\s*[-–]\s*(\d+)/i.exec(error.detail)
    return range ? `Please choose a move from ${range[1]}–${range[2]} for this clip.` : 'That analysis or move is no longer available. Please resend the clip or choose a move number from its list.'
  }
  if (error.status === 400) return 'Please send a supported video, or reply with a move number from your latest analysis.'
  if (error.status === 408) return 'This analysis is taking too long. Please try a shorter clip.'
  if (error.status === 422) return 'I couldn’t read that video. Can you try another clip?'
  return 'The video analysis service is unavailable after a retry. Please try again shortly; its temporary tunnel may need updating.'
}

export function createMessagingAgentApi({ baseUrl, fetchImpl = fetch, sleep = delay, timeoutMs = 20 * 60 * 1000 }) {
  const base = new URL(baseUrl)
  if (base.protocol !== 'https:' || base.username || base.password || base.search || base.hash) throw new Error('MESSAGING_AGENT_API_URL must be an HTTPS URL')
  const endpoint = base.href.replace(/\/$/, '')
  const validId = id => typeof id === 'string' && /^[\w-]{1,100}$/.test(id)
  async function request(path, body, key, deadline) {
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const remaining = deadline - Date.now()
        if (remaining <= 0) throw new AgentApiError(408)
        const form = body instanceof FormData
        const response = await fetchImpl(`${endpoint}${path}`, {
          method: body === undefined ? 'GET' : 'POST',
          ...(body === undefined ? {} : { body: form ? body : JSON.stringify(body) }),
          headers: { ...(body === undefined || form ? {} : { 'Content-Type': 'application/json' }), 'Idempotency-Key': key },
          redirect: 'error', signal: AbortSignal.timeout(Math.min(90000, remaining)) })
        const data = await response.json().catch(() => ({}))
        if (!response.ok) throw new AgentApiError(response.status, data.detail)
        if (!validId(data.analysis_id)) throw new AgentApiError(502)
        if (response.status === 202 && data.status === 'processing') return data
        if (typeof data.message !== 'string' || !data.message.trim() || data.message.length > 60000) throw new AgentApiError(502)
        return data
      } catch (error) {
        const failure = error instanceof AgentApiError ? error : new AgentApiError(0)
        if (!failure.retryable || attempt === 1) throw failure
        await sleep(1000)
      }
    }
  }
  async function finish(data, key, { onPending = async () => {}, deadline = Date.now() + timeoutMs } = {}) {
    const id = data.analysis_id
    while (data.status === 'processing') {
      await onPending(data)
      const seconds = Number(data.retry_after_s)
      const waitMs = Number.isFinite(seconds) && seconds > 0 ? Math.max(1000, Math.min(60000, seconds * 1000)) : 15000
      if (Date.now() + waitMs >= deadline) throw new AgentApiError(408)
      await sleep(waitMs)
      data = await request(`/agent/analysis/${encodeURIComponent(id)}`, undefined, key, deadline)
      if (data.analysis_id !== id) throw new AgentApiError(502)
    }
    return data
  }
  return {
    origin: base.origin,
    async analyze(form, key, options = {}) {
      const deadline = options.deadline ?? Date.now() + timeoutMs
      return finish(await request('/agent/analyze', form, key, deadline), key, { ...options, deadline })
    },
    analysis: (id, key, options = {}) => {
      if (!validId(id)) throw new AgentApiError(400)
      return finish({ analysis_id: id, status: 'processing' }, key, options)
    },
    move: (body, key) => request('/agent/move', body, key, Date.now() + timeoutMs),
    async video(url) {
      const target = new URL(url, base)
      if (target.origin !== base.origin || target.username || target.password) throw new Error('API returned a video outside its configured origin')
      const response = await fetchImpl(target.href, { signal: AbortSignal.timeout(120000), redirect: 'error' })
      if (!response.ok) throw new Error('Move video download failed')
      const chunks = []
      let size = 0
      for await (const chunk of response.body) {
        size += chunk.length
        if (size > MAX_BYTES) throw new Error('Move video exceeds the iMessage size limit')
        chunks.push(chunk)
      }
      if (!size) throw new Error('Move video is empty')
      return new Uint8Array(Buffer.concat(chunks))
    },
  }
}

export function createMessagingAgentHandler({ student, agentId, authorize, memory, muted, download, upload, send,
  saveReport = async () => {}, api, directory = join(process.cwd(), '.coach', 'messaging-agent'),
  programType = 'unk', perceptronTrack = true, ignoreBefore = 0, onError = () => console.error('Messaging API delivery pending; retrying shortly.') }) {
  if (!['unk', 'sp', 'fs'].includes(programType)) throw new Error('Invalid messaging API program type')
  const events = join(directory, 'events'), chats = join(directory, 'chats')
  const pending = new Map(), active = new Map(), busy = new Set()
  const chatWrites = new Map()
  const spaceKey = message => hash(`${agentId}:${message.space.id}`)
  async function load(path) {
    try { return JSON.parse(await readFile(path, 'utf8')) }
    catch (error) { if (error.code === 'ENOENT') return null; throw error }
  }
  async function save(path, value) {
    await writeFile(`${path}.tmp`, JSON.stringify(value), { mode: 0o600 })
    await rename(`${path}.tmp`, path)
  }
  const eventPath = state => join(events, `${hash(state.message.id)}.json`)
  const chatPath = message => join(chats, `${spaceKey(message)}.json`)
  async function updateChat(message, change) {
    const key = spaceKey(message)
    const work = (chatWrites.get(key) || Promise.resolve()).catch(() => {}).then(async () => {
      const value = change(await load(chatPath(message)))
      if (value) await save(chatPath(message), value)
    })
    chatWrites.set(key, work)
    try { await work } finally { if (chatWrites.get(key) === work) chatWrites.delete(key) }
  }
  async function permitted(message) {
    if (ignoreBefore && (!Number.isFinite(Date.parse(message.createdAt)) || Date.parse(message.createdAt) <= ignoreBefore)) return false
    if (message.platform !== 'imessage' || (message.space.kind !== 'group' && message.sentBy.handle !== student)) return false
    await authorize(message.space.id, message.sentBy.handle)
    return !(await memory.get()).paused && !(message.space.kind === 'group' && await muted(message.space.id))
  }
  async function text(state, value, suffix) {
    if (!await permitted(state.message)) return false
    const result = await send({ senderId: agentId, spaceId: state.message.space.id, replyTo: state.message.nativeMessageId,
      voiceEligible: false, content: { type: 'text', format: 'plain', text: value } }, `dh26-api-${state.message.id}-${suffix}`)
    if (result.status === 'failed') throw new Error('API text delivery failed')
    return true
  }
  async function run(state) {
    if (state.done || !await permitted(state.message)) return
    if (!state.result && !state.error) {
      if (!await text(state, state.kind === 'analyze' ? 'Analysing your clip… I’ll send the move list when it’s ready.' : 'Preparing that move’s breakdown and video…', 'working')) return
      try {
        if (state.kind === 'analyze') {
          const options = { deadline: state.analysisDeadline ?? Date.now() + 20 * 60 * 1000, onPending: async data => {
            state.processingId = data.analysis_id
            state.analysisDeadline = options.deadline
            await save(eventPath(state), state)
          } }
          if (state.processingId) {
            state.result = await api.analysis(state.processingId, state.message.id, options)
          } else {
            const chunks = []; let size = 0
            for await (const chunk of download(state.attachment.guid)) {
              if (chunk.type !== 'primaryChunk') continue
              size += chunk.data.length
              if (size > MAX_BYTES) throw new AgentApiError(400)
              chunks.push(chunk.data)
            }
            if (!size) throw new AgentApiError(422)
            if (!await permitted(state.message)) return
            const form = new FormData()
            form.set('video', new Blob(chunks), state.fileName)
            form.set('program_type', programType)
            form.set('perceptron_track', String(perceptronTrack))
            state.result = await api.analyze(form, state.message.id, options)
          }
        } else {
          state.result = await api.move({ analysis_id: state.analysisId, move: state.move, view: state.view || 'normal' }, state.message.id)
          if (state.result.analysis_id !== state.analysisId) throw new AgentApiError(502)
        }
      } catch (error) { state.result = null; state.error = agentErrorMessage(error) }
      await save(eventPath(state), state)
    }
    if (state.error) {
      if (state.kind === 'analyze') await updateChat(state.message, chat => chat?.uploadId === state.message.id ? { ...chat, failed: true } : null)
      if (await text(state, state.error, 'error')) { state.done = true; await save(eventPath(state), state) }
      return
    }
    if (state.kind === 'analyze' && !state.reportSaved) {
      if (!await permitted(state.message)) return
      await saveReport({ analysisId: state.result.analysis_id, fileName: state.fileName, report: state.result.message })
      state.reportSaved = true
      await save(eventPath(state), state)
    }
    if (state.kind === 'analyze') {
      await updateChat(state.message, chat => chat?.uploadId === state.message.id ? { ...chat,
        analysisId: state.result.analysis_id, message: state.result.message,
        hasMoves: /^\s*\d+\.\s/m.test(state.result.message), ready: true } : null)
    }
    if (!state.textSent) {
      if (!await text(state, state.result.message, 'result')) return
      state.textSent = true
      await save(eventPath(state), state)
    }
    if (state.kind === 'move') {
      for (const field of ['video_url', 'skeleton_video_url']) {
        const url = state.result[field]
        if (!url || state[`${field}_sent`]) continue
        if (!await permitted(state.message)) return
        if (!state[`${field}_guid`]) {
          const data = await api.video(url)
          if (!await permitted(state.message)) return
          const result = await upload({ data, fileName: field === 'skeleton_video_url' || state.view === 'skeleton' ? 'move_skeleton.mp4' : 'move.mp4' })
          if (!result.attachment?.guid) throw new Error('Move video upload failed')
          state[`${field}_guid`] = result.attachment.guid
          await save(eventPath(state), state)
        }
        if (!await permitted(state.message)) return
        const result = await send({ senderId: agentId, spaceId: state.message.space.id, replyTo: state.message.nativeMessageId,
          content: { type: 'attachment', guid: state[`${field}_guid`] } }, `dh26-api-${state.message.id}-${field}`)
        if (result.status === 'failed') throw new Error('Move video delivery failed')
        state[`${field}_sent`] = true
        await save(eventPath(state), state)
      }
    }
    if (state.kind === 'move') {
      await updateChat(state.message, chat => chat?.analysisId === state.analysisId ? { ...chat, lastMove: state.move } : null)
      if (!state.offerSent) {
        if (!await text(state, state.view === 'skeleton' ? 'Want the original footage? Reply “normal”.' : 'Want the skeleton overlay? Reply “skeleton”.', 'view-offer')) return
        state.offerSent = true
      }
    }
    state.done = true
    await save(eventPath(state), state)
  }
  function pump() {
    for (const [id, state] of pending) {
      if (active.size >= 2) break
      const space = spaceKey(state.message)
      if (busy.has(space)) continue
      pending.delete(id); busy.add(space)
      const work = run(state).catch(onError).finally(() => { active.delete(id); busy.delete(space); pump() })
      active.set(id, work)
    }
  }
  async function enqueue(state) {
    if (!state.done && !active.has(state.message.id)) { pending.set(state.message.id, state); pump() }
  }
  return {
    async handle(message, attachments = []) {
      const videos = attachments.filter(file => !file.isHidden && !file.isSticker &&
        (file.mimeType?.startsWith('video/') || VIDEO_EXTENSIONS.has(extname(file.fileName || '').toLowerCase())))
      const rawText = message.content?.type === 'text' ? message.content.text.trim() : ''
      const move = moveRequest(rawText)
      const view = /\bskeleton\b/i.test(rawText) ? 'skeleton' : 'normal'
      const viewOnly = /\b(skeleton|normal|original)\b/i.test(rawText)
      if (!videos.length && !move && !viewOnly) return false
      if (!await permitted(message)) return true
      await mkdir(events, { recursive: true, mode: 0o700 }); await mkdir(chats, { recursive: true, mode: 0o700 })
      let state = await load(join(events, `${hash(message.id)}.json`))
      if (state) { await enqueue(state); return true }
      if (videos.length) {
        const file = videos[0], fileName = basename((file.fileName || 'skating.mp4').replaceAll('\\', '/')).slice(0, 150)
        state = { message, kind: 'analyze', attachment: { guid: file.guid }, fileName }
        if (videos.length !== 1 || file.totalBytes > MAX_BYTES || !VIDEO_EXTENSIONS.has(extname(fileName).toLowerCase())) {
          await text(state, 'Please send one supported video at a time, under 199 MB.', 'invalid')
          state.done = true
        } else await updateChat(message, () => ({ uploadId: message.id, ready: false }))
      } else {
        const chat = await load(chatPath(message))
        if (!chat) return false
        if (chat.failed) { await text({ message }, 'Your latest clip could not be analysed. Please resend it to try again.', 'failed'); return true }
        if (!chat.ready) { await text({ message }, 'Your latest clip is still being analysed. Wait for its numbered move list before choosing a move.', 'pending'); return true }
        if (!chat.hasMoves) { await text({ message }, 'No numbered moves were found in your latest clip. Please send another video.', 'no-moves'); return true }
        const selectedMove = move || chat.lastMove
        if (!selectedMove) { await text({ message }, 'Which move number would you like to see?', 'choose-move'); return true }
        state = { message, kind: 'move', analysisId: chat.analysisId, move: selectedMove, view }
      }
      await save(eventPath(state), state)
      await enqueue(state)
      return true
    },
    async resume() {
      await mkdir(events, { recursive: true, mode: 0o700 }); await mkdir(chats, { recursive: true, mode: 0o700 })
      const states = []
      for (const name of await readdir(events)) if (/^[a-f0-9]{64}\.json$/.test(name)) {
        const state = await load(join(events, name))
        if (state && !state.done && ignoreBefore && (!Number.isFinite(Date.parse(state.message.createdAt)) || Date.parse(state.message.createdAt) <= ignoreBefore)) {
          state.done = true
          state.ignoredBefore = new Date(ignoreBefore).toISOString()
          await save(join(events, name), state)
        }
        if (state && !state.done) states.push(state)
      }
      states.sort((a, b) => (a.message.createdAt || '').localeCompare(b.message.createdAt || ''))
      for (const state of states) await enqueue(state)
    },
    async drain() { while (active.size || pending.size) { pump(); await Promise.all([...active.values()]) } },
  }
}
