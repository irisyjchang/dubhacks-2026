import { createIncomingVideoHandler } from './imessage-video.mjs'
import { createVoiceNotes, sendVoiceNote } from './voice-notes.mjs'
import { Spectrum, cloud } from 'spectrum-ts'
import { setTimeout as delay } from 'node:timers/promises'
import { imessage } from 'spectrum-ts/providers/imessage'
import { createGrpcClient } from '@photon-ai/advanced-imessage/grpc'
import { startCoachServer, respondWithCoach, resetCoachConversation, photonDelivery,
  athleteMemory, groupCoaching, setTextTransport, flushReportNotifications, voiceCallContext, saveMessagingAnalysis } from './coach-state.mjs'
import { createMessagingAgentApi, createMessagingAgentHandler } from './messaging-agent.mjs'
import { createMessageActivity } from './message-activity.mjs'
import { createPhotonHandler } from './photon-handler.mjs'
import { createNativeGroupHandler } from './photon-group-handler.mjs'
import { createCallGateway, readCallConfig, createHostedCallSync } from './photon-calls.mjs'
import { canonicalHandle, normalizeSpectrumMessage, spectrumMembers, assertCoachChat } from './spectrum-adapter.mjs'

for (const key of ['SPECTRUM_PROJECT_ID', 'SPECTRUM_PROJECT_SECRET', 'PHOTON_PHONE_NUMBER', 'PHOTON_ALLOWED_SENDER', 'OPENAI_API_KEY']) {
  if (!process.env[key]) throw new Error(`Missing ${key} in .env`)
}
const number = canonicalHandle(process.env.PHOTON_PHONE_NUMBER)
const student = canonicalHandle(process.env.PHOTON_ALLOWED_SENDER)
const agentId = `spectrum:${number}`
const ignoreBefore = process.env.PHOTON_IGNORE_BEFORE ? Date.parse(process.env.PHOTON_IGNORE_BEFORE) : 0
if (!Number.isFinite(ignoreBefore)) throw new Error('PHOTON_IGNORE_BEFORE must be an ISO timestamp')
const credentials = [process.env.SPECTRUM_PROJECT_ID, process.env.SPECTRUM_PROJECT_SECRET]
const status = { ready: false, connection: 'spectrum', channel: 'imessage', number, agentId,
  groupAccess: 'current members', reason: 'Connecting dedicated line',
  groupChatReady: false, groupChatReason: 'Connecting dedicated line', eventStream: 'connecting' }
let app, remote, videoHandler, timer, running = true, flushing = false
const shutdownSignal = new AbortController()
const pause = milliseconds => delay(milliseconds, undefined, { signal: shutdownSignal.signal }).catch(() => {})
let tokenData, refreshAt = 0, refresh
const server = await startCoachServer()
let callServer, callSyncTimer
if (process.env.PHOTON_CALLS_ENABLED === 'true') {
  try {
    const config = await readCallConfig()
    if (!config?.agentId || !config?.phoneNumberId || config.number !== number || canonicalHandle(config.owner) !== student) throw new Error('Run npm run calls:setup for this line first')
    if (config.mode === 'hosted') {
      const sync = createHostedCallSync({ config, context: () => voiceCallContext(config.access === 'group') })
      status.calling = { enabled: true, mode: 'hosted', provider: 'elevenlabs-sip', inboundRouteRequired: true, ...await sync() }
      let syncing = false
      callSyncTimer = setInterval(async () => {
        if (syncing) return
        syncing = true
        try { Object.assign(status.calling, await sync(), { reason: null }) }
        catch { Object.assign(status.calling, { ready: false, reason: 'Voice context sync unavailable' }) }
        finally { syncing = false }
      }, 15000)
    } else {
      callServer = createCallGateway({ token: config.token, number, owner: student,
        memory: athleteMemory, answer: respondWithCoach })
      await new Promise((resolve, reject) => {
        callServer.once('error', reject)
        callServer.listen(Number(process.env.CALLS_PORT || 8789), '127.0.0.1', resolve)
      })
      status.calling = { enabled: true, gatewayReady: true, provider: 'elevenlabs-sip',
        inboundRouteRequired: true }
    }
  } catch (error) {
    status.calling = { enabled: true, gatewayReady: false, reason: error.message }
    console.error('Calling gateway unavailable:', error.message)
  }
} else status.calling = { enabled: false, gatewayReady: false }
server.once('close', () => { callServer?.close(); clearInterval(callSyncTimer) })

async function tokens() {
  if (tokenData && Date.now() < refreshAt) return tokenData
  if (refresh) return refresh
  refresh = cloud.issueImessageTokens(...credentials).then(data => {
    if (data.type !== 'dedicated' || !Object.values(data.numbers).includes(number)) {
      throw new Error('The configured dedicated number is not owned by this Spectrum project')
    }
    tokenData = data
    refreshAt = Date.now() + Math.max(1000, data.expiresIn * 800)
    return data
  }).finally(() => { refresh = null })
  return refresh
}

const prepareVoice = createVoiceNotes()

async function send(body, key) {
  if (!status.ready || body.senderId !== agentId) throw new Error('Sending from an inactive AI number is disabled')
  const chat = await remote.chats.get(body.spaceId)
  assertCoachChat(chat, { spaceId: body.spaceId, number, student })
  // Presence is best effort; a receipt failure must not block a saved reply.
  await remote.chats.markRead(body.spaceId).catch(() => {})
  const voice = body.voiceEligible
    ? await prepareVoice(key, body.content.text, input => remote.attachments.upload(input)) : { type: 'text' }
  // Recheck membership after speech generation, before delivering shared feedback.
  assertCoachChat(await remote.chats.get(body.spaceId), { spaceId: body.spaceId, number, student })
  const options = { clientMessageId: key, ...(body.replyTo ? { replyTo: body.replyTo } : {}) }
  let message
  try {
    message = body.content.type === 'attachment'
      ? await remote.messages.sendAttachment(body.spaceId, body.content.guid, options)
      : voice.type === 'audio'
      ? await sendVoiceNote(remote, body.spaceId, voice.guid, key)
      : await remote.messages.sendText(body.spaceId, body.content.text, options)
  } catch (error) {
    // Photon uses this response when the original stable-key send succeeded.
    if (error.code !== 'duplicateMessage') throw error
    message = { isDelivered: false }
  }
  if (message.sendErrorCode) throw new Error('Photon reported an iMessage send error')
  status.lastReplyAt = new Date().toISOString()
  status.lastReplyStatus = message.isDelivered ? 'delivered' : 'submitted'
  return { status: message.isDelivered ? 'delivered' : 'submitted', id: message.guid }
}
async function react(message, reaction) {
  if (!status.ready) throw new Error('Dedicated line is inactive')
  const spaceId = message.space.id
  assertCoachChat(await remote.chats.get(spaceId), { spaceId, number, student })
  const result = await remote.messages.setReaction(spaceId, message.nativeMessageId, reaction, true, {
    clientMessageId: `dh26-reaction-${message.id}`,
  })
  if (result.sendErrorCode) throw new Error('Photon reaction failed')
}
setTextTransport({ status: () => ({ ...status }), send })

async function connect() {
  const data = await tokens()
  const instanceId = Object.keys(data.numbers).find(id => data.numbers[id] === number)
  remote = createGrpcClient({ address: `${instanceId}.imsg.photon.codes:443`, tls: true,
    retry: true, timeout: 30000, autoIdempotency: true,
    token: async () => {
      const current = await tokens()
      if (current.numbers[instanceId] !== number || !current.auth[instanceId]) throw new Error('Dedicated line is no longer available')
      return current.auth[instanceId]
    } })
  try {
    app = await Spectrum({ projectId: credentials[0], projectSecret: credentials[1],
      providers: [imessage.config()], options: { logLevel: 'warn', flattenGroups: false } })
  } catch (error) { await remote.close(); remote = null; throw error }
  if (!running) { await app.stop(); await remote.close(); return }
  const im = imessage(app)
  const profile = await athleteMemory.get()
  if (profile.route && profile.route.senderId !== agentId) await athleteMemory.set({ route: null })
  status.ready = true
  status.reason = null
  status.lineType = 'dedicated'
  status.projectName = app.config.name
  status.groupChatReady = true
  status.groupChatReason = null

  const handle = createPhotonHandler({ allowedSender: student, agentId, platform: 'imessage',
    delivery: photonDelivery, memory: athleteMemory, answer: respondWithCoach, reset: resetCoachConversation, send, react,
    withActivity: createMessageActivity({
      authorize: async spaceId => assertCoachChat(await remote.chats.get(spaceId), { spaceId, number, student }),
      chats: remote.chats,
    }) })
  const handleGroup = createNativeGroupHandler({ studentHandle: student, agentId,
    withActivity: createMessageActivity({
      authorize: async spaceId => assertCoachChat(await remote.chats.get(spaceId), { spaceId, number, student }),
      chats: remote.chats,
    }),
    groupCapable: () => status.groupChatReady, groups: groupCoaching, delivery: photonDelivery, send, react,
    members: async spaceId => {
      const space = await im.space.get(spaceId, { phone: number })
      return spectrumMembers(await space.getMembers(), number, agentId)
    } })

  const messagingApi = process.env.MESSAGING_AGENT_API_URL
    ? createMessagingAgentApi({ baseUrl: process.env.MESSAGING_AGENT_API_URL }) : null
  status.videoBackend = messagingApi ? { type: 'messaging-agent-api', origin: messagingApi.origin } : { type: 'local-backend', port: 8001 }
  videoHandler ||= (messagingApi ? createMessagingAgentHandler : createIncomingVideoHandler)({ student, agentId, memory: athleteMemory, ignoreBefore,
    ...(messagingApi ? { api: messagingApi, saveReport: saveMessagingAnalysis,
      programType: process.env.MESSAGING_AGENT_PROGRAM_TYPE || 'unk',
      perceptronTrack: process.env.MESSAGING_AGENT_PERCEPTRON_TRACK !== 'false' } : {}),
    authorize: async (spaceId, sender) => {
      const chat = await remote.chats.get(spaceId)
      assertCoachChat(chat, { spaceId, number, student })
      if (!chat.participants.some(person => canonicalHandle(person.address || person.id) === sender)) {
        const error = new Error('Video sender is no longer in this conversation')
        error.code = 'COACH_CHAT_NOT_AUTHORIZED'
        throw error
      }
    },
    muted: spaceId => groupCoaching.muted(spaceId),
    download: guid => remote.attachments.downloadStream(guid),
    upload: input => remote.attachments.upload(input), send,
  })
  await videoHandler.resume()

  // Reopen the existing group. Current members all participate equally.
  const savedGroup = profile.groupRoute
  if (savedGroup?.agentId === agentId) {
    try {
      const chat = await remote.chats.get(savedGroup.spaceId)
      assertCoachChat(chat, { spaceId: chat.guid, number, student })
      await athleteMemory.set({ groupRoute: { agentId, spaceId: chat.guid } })
      status.groupSpaceId = chat.guid
    } catch { status.groupSetupError = 'Start an iMessage group that includes your number and the AI.' }
  }
  timer = setInterval(() => {
    void videoHandler.resume().catch(() => console.error('Video queue resume pending.'))
    if (flushing) return
    flushing = true
    flushReportNotifications().catch(() => console.error('Report follow-up pending; retrying.')).finally(() => { flushing = false })
  }, 30000)
  status.eventStream = 'listening'
  console.log(`Spectrum coach listening on dedicated iMessage ${number}.`)
  // The SDK reconnects its gRPC stream and catches up after interruptions.
  // Failed message work retries the saved outbox body before advancing locally.
  for await (const [space, message] of app.messages) {
    const incoming = normalizeSpectrumMessage(imessage(space), message, number, agentId, ignoreBefore)
    if (!incoming) continue
    status.lastReceivedAt = new Date().toISOString()
    while (running) {
      try {
        // Fetch canonical attachment metadata; never trust an inbound URL.
        const raw = await remote.messages.get(incoming.nativeMessageId)
        if (await videoHandler.handle(incoming, raw.content.attachments)) break
        await (incoming.space.kind === 'group' ? handleGroup(incoming) : handle(incoming))
        break
      } catch (error) {
        status.lastMessageErrorCode = error.code || error.name
        if (error.code === 'COACH_CHAT_NOT_AUTHORIZED') break
        console.error('Coach message pending; retrying the saved reply.', error.code || error.name, String(error.message).replace(/(?:sk_|Bearer\s+)\S+/g, '[redacted]').slice(0, 400))
        await pause(5000)
      }
    }
  }
  if (running) throw new Error('Spectrum message stream ended')
}

async function run() {
  while (running) {
    try { await connect() }
    catch (error) {
      status.ready = status.groupChatReady = false
      status.reason = 'Spectrum connection unavailable; retrying'
      status.groupChatReason = status.reason
      status.eventStream = 'reconnecting'
      status.lastErrorCode = error.code || error.name
      console.error(status.reason, status.lastErrorCode)
    } finally {
      clearInterval(timer)
      await app?.stop().catch(() => {})
      await remote?.close().catch(() => {})
      app = remote = null
    }
    if (running) await pause(10000)
  }
}
async function shutdown() {
  running = false
  status.ready = status.groupChatReady = false
  clearInterval(timer)
  shutdownSignal.abort()
  await app?.stop().catch(() => {})
  await remote?.close().catch(() => {})
  callServer?.close()
  clearInterval(callSyncTimer)
  server.close()
}
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => { void shutdown() })
await run()
