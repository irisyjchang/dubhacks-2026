import { io } from 'socket.io-client'
import { respondWithCoach, resetCoachConversation, startCoachServer, photonDelivery,
  athleteMemory, setTextTransport, flushReportNotifications, groupCoaching } from './coach-state.mjs'
import { createPhotonHandler } from './photon-handler.mjs'
import { createNativeGroupHandler } from './photon-group-handler.mjs'

for (const key of ['PHOTON_PROJECT_ID', 'PHOTON_API_KEY', 'PHOTON_ALLOWED_SENDER', 'OPENAI_API_KEY']) {
  if (!process.env[key]) throw new Error(`Missing ${key} in .env`)
}
const platform = process.env.PHOTON_CHANNEL || 'imessage'
if (!['sms', 'imessage'].includes(platform)) throw new Error('PHOTON_CHANNEL must be imessage or sms')
const origin = 'https://api.photon.codes'
const base = `${origin}/v1/projects/${process.env.PHOTON_PROJECT_ID}`
const startedAt = new Date().toISOString()
const status = { ready: false, channel: platform, number: process.env.PHOTON_PHONE_NUMBER,
  reason: 'Checking line', eventStream: 'connecting' }
let running = true
let work = Promise.resolve()
let polling = false
let flushing = false

async function photon(path, options = {}) {
  const response = await fetch(`${base}${path}`, {
    ...options,
    headers: { Authorization: `Bearer ${process.env.PHOTON_API_KEY}`, 'Content-Type': 'application/json', ...options.headers },
    signal: AbortSignal.timeout(30000),
  })
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}))
    throw new Error(`Photon HTTP ${response.status}${problem.code ? ` (${problem.code})` : ''}`)
  }
  return response.json()
}
const send = (body, key) => {
  if (!status.ready) throw new Error(status.reason)
  if (body.senderId !== status.agentId) throw new Error('Sending from an inactive AI number is disabled')
  return photon('/messages', { method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(body) })
}
const coachServer = await startCoachServer()
setTextTransport({ status: () => ({ ...status }), send })
async function connectPhoton() {
const users = await photon(`/users?platform=${platform}&pageSize=100`)
const agents = users.items.filter(user => user.kind === 'agent')
const agent = agents.find(user => user.handle === status.number)
if (!agent) throw new Error(`The configured number ${status.number} is not available in this Photon project's ${platform} agents`)
status.agentId = agent.id
const profile = await athleteMemory.get()
if (profile.route && (profile.route.senderId !== agent.id || profile.route.platform !== platform)) {
  await athleteMemory.set({ route: null })
}
status.lineType = agent.details?.type || (platform === 'sms' ? 'sms' : 'unknown')
async function refreshEligibility() {
  if (platform === 'sms') {
    const assignment = await photon(`/platforms/sms/lines/${agent.details.resourceId}/campaign`)
    status.ready = assignment.eligibility !== 'blocked'
    status.reason = status.ready ? null : assignment.reasonCode
  } else {
    await photon('/platforms/imessage')
    status.ready = true
    status.reason = null
  }
  status.groupChatReady = status.ready && (platform === 'sms' || status.lineType === 'dedicated')
  status.groupChatReason = !status.ready ? status.reason : status.groupChatReady ? null : 'Native iMessage groups require a dedicated line. Use the local group preview meanwhile.'
}
await refreshEligibility()
const handle = createPhotonHandler({ allowedSender: process.env.PHOTON_ALLOWED_SENDER,
  agentId: agent.id, platform, delivery: photonDelivery, memory: athleteMemory,
  answer: respondWithCoach, reset: resetCoachConversation, send })
const handleGroup = createNativeGroupHandler({ studentHandle: process.env.PHOTON_ALLOWED_SENDER,
  agentId: agent.id, platform,
  groupCapable: () => status.groupChatReady,
  members: async spaceId => {
    const space = await photon(`/spaces/${spaceId}`)
    if (space.kind !== 'group' || space.platform !== platform || space.participantIds.length < 2) return []
    return Promise.all(space.participantIds.map(id => photon(`/users/${id}`)))
  }, groups: groupCoaching, delivery: photonDelivery, send })
function enqueue(message) {
  const task = work.catch(() => {}).then(() => message.space?.kind === 'group' ? handleGroup(message) : handle(message))
  work = task
  return task
}

let cursor = await athleteMemory.cursor(platform)
const firstConnection = cursor === null
cursor ??= 0
let epoch = 0
let pending = 0
let events = Promise.resolve()
const socket = io(origin, { path: `/v1/projects/${process.env.PHOTON_PROJECT_ID}/events/ws`,
  addTrailingSlash: false, transports: ['websocket'],
  extraHeaders: { Authorization: `Bearer ${process.env.PHOTON_API_KEY}` }, autoConnect: false })
socket.on('connect', () => {
  socket.timeout(10000).emit('subscribe', { startSeq: cursor, apiVersion: '2026-07-01' }, (error, result) => {
    if (error || !result?.ok) {
      status.eventStream = result?.error?.code || 'retrying'
      socket.io.engine.close()
      return
    }
    status.eventStream = 'live'
    console.log('Photon beta event stream connected with durable replay.')
  })
})
socket.on('disconnect', () => { epoch++; status.eventStream = 'reconnecting' })
socket.on('delivery', (event, metadata) => {
  const generation = epoch
  const seq = metadata?.seq
  if (!Number.isSafeInteger(seq) || seq < 0) return
  if (++pending > 128) { pending--; epoch++; socket.io.engine.close(); return }
  events = events.then(async () => {
    if (generation !== epoch || seq <= cursor) return
    const message = event.data?.object
    if (event.type === 'message.received' && event.data?.projectId === process.env.PHOTON_PROJECT_ID &&
        message?.platform === platform && message.status === 'received' &&
        !(firstConnection && message.createdAt < startedAt)) {
      await enqueue(message)
    }
    await athleteMemory.checkpoint(platform, seq)
    cursor = seq
  }).catch(error => {
    console.error('Event handling will retry:', error.message)
    if (generation === epoch) { epoch++; socket.io.engine.close() }
  }).finally(() => { pending-- })
})
socket.on('connect_error', () => { status.eventStream = 'polling fallback' })
socket.on('delivery_error', error => { console.error('Photon event error:', error.code) })
socket.connect()

// Reconcile recent received messages if the live stream is temporarily unavailable.
// Both paths share the same serial handler and MongoDB outbox.
async function reconcile() {
  if (!running || polling) return
  polling = true
  try {
    let token
    do {
      const query = new URLSearchParams({ platform, direction: 'received', createdSince: startedAt, order: 'asc', pageSize: '200' })
      if (token) query.set('pageToken', token)
      const page = await photon(`/messages?${query}`)
      for (const message of page.items) await enqueue(message)
      token = page.nextPageToken
    } while (token && running)
  } catch (error) { console.error('Message reconciliation will retry:', error.message) }
  finally { polling = false }
}
const pollTimer = setInterval(() => { void reconcile() }, 15000)
const followupTimer = setInterval(() => {
  if (flushing) return
  flushing = true
  refreshEligibility().then(flushReportNotifications).catch(error => console.error('Follow-up pending:', error.message))
    .finally(() => { flushing = false })
}, 30000)
console.log(`Photon 2.0 beta coach: ${status.number} (${platform}); ${status.ready ? 'ready' : status.reason}`)
async function shutdown() {
  if (!running) return
  running = false
  clearInterval(pollTimer)
  clearInterval(followupTimer)
  socket.disconnect()
  await work.catch(() => {})
  coachServer.close()
}
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => { void shutdown() })
}

function retryConnection(error) {
  status.ready = false
  status.reason = error.message
  status.eventStream = 'waiting for configured line'
  status.groupChatReady = false
  status.groupChatReason = error.message
  console.error('Photon connection pending:', error.message)
  setTimeout(() => { void connectPhoton().catch(retryConnection) }, 30000)
}
await connectPhoton().catch(retryConnection)
