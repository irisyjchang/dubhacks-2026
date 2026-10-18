import { MongoClient } from 'mongodb'
import { createHash, randomUUID } from 'node:crypto'

export function analysisId(analysis) {
  const { savedAt, id, _id, owner, ...measurements } = analysis
  return createHash('sha256').update(JSON.stringify(measurements)).digest('hex')
}

export function timelineFilter(owner, cursor) {
  const filter = { owner, source: 'spincoach', 'feedback.report': { $type: 'string' } }
  if (cursor) {
    let time, id
    try { [time, id] = JSON.parse(Buffer.from(cursor, 'base64url').toString()) } catch { throw new Error('Invalid timeline cursor') }
    if (typeof time !== 'string' || !Number.isFinite(Date.parse(time)) || typeof id !== 'string' || !/^[a-f0-9]{64}$/.test(id)) throw new Error('Invalid timeline cursor')
    filter.$or = [{ savedAt: { $lt: time } }, { savedAt: time, _id: { $lt: `${owner}:${id}` } }]
  }
  return filter
}

export async function openCoachDatabase({ uri = process.env.MONGODB_URI || 'mongodb://127.0.0.1:27017',
  name = process.env.MONGODB_DB || 'figure_skating_coach',
  owner = process.env.PHOTON_ALLOWED_SENDER || 'local-demo' } = {}) {
  const client = new MongoClient(uri, { serverSelectionTimeoutMS: 5000 })
  try {
    await client.connect()
    const db = client.db(name)
    await db.command({ ping: 1 })
    const analyses = db.collection('analyses')
    const conversations = db.collection('coach_conversations')
    const deliveries = db.collection('photon_replies')
    const athletes = db.collection('coach_athletes')
    const journal = db.collection('coach_journal')
    const checkpoints = db.collection('photon_checkpoints')
    const rooms = db.collection('coach_rooms')
    const roomMessages = db.collection('coach_room_messages')
    await analyses.createIndex({ owner: 1, savedAt: -1, _id: -1 })
    await conversations.createIndex({ owner: 1, createdAt: -1, _id: -1 })
    await journal.createIndex({ owner: 1, createdAt: -1 })
    await rooms.createIndex({ owner: 1, createdAt: -1 })
    await roomMessages.createIndex({ owner: 1, roomId: 1, sequence: -1 })
    return {
      async save(analysis) {
        const id = analysisId(analysis)
        const result = await analyses.updateOne({ _id: `${owner}:${id}` }, {
          $setOnInsert: { ...analysis, id, owner },
        }, { upsert: true })
        return { ...analysis, id, inserted: result.upsertedCount === 1 }
      },
      async list() {
        const rows = await analyses.find({ owner }, { projection: { _id: 0, owner: 0 } })
          .sort({ savedAt: -1, _id: -1 }).limit(20).toArray()
        return rows.reverse()
      },
      async latestFeedback() {
        return analyses.findOne({ owner, source: 'spincoach', 'feedback.report': { $type: 'string' } },
          { projection: { _id: 0, owner: 0 }, sort: { savedAt: -1, _id: -1 } })
      },
      async feedbackTimeline(cursor) {
        const rows = await analyses.find(timelineFilter(owner, cursor), { projection: {
          _id: 0, id: 1, videoName: 1, savedAt: 1,
          'feedback.headline': 1, 'feedback.findings': 1, 'feedback.provenance': 1, 'feedback.durationSeconds': 1,
        } }).sort({ savedAt: -1, _id: -1 }).limit(11).toArray()
        const items = rows.slice(0, 10)
        const last = items.at(-1)
        return { items, nextCursor: rows.length > 10 ? Buffer.from(JSON.stringify([last.savedAt, last.id])).toString('base64url') : null }
      },
      async feedbackById(id) {
        if (!/^[a-f0-9]{64}$/.test(id)) return null
        return analyses.findOne({ ...timelineFilter(owner), id }, { projection: {
          _id: 0, id: 1, videoName: 1, savedAt: 1, feedback: 1,
        } })
      },
      async recentFeedback(limit = 5) {
        const rows = await analyses.find(timelineFilter(owner), { projection: { _id: 0, owner: 0 } })
          .sort({ savedAt: -1, _id: -1 }).limit(limit).toArray()
        return rows.reverse()
      },
      async athlete() {
        const profile = await athletes.findOne({ _id: owner })
        const notes = await journal.find({ owner }, { projection: { _id: 0, owner: 0 } }).sort({ createdAt: -1 }).limit(10).toArray()
        return { goal: profile?.goal || null, notifications: profile?.notifications === true,
          paused: profile?.paused === true, route: profile?.route || null,
          groupRoute: profile?.groupRoute || null, notes: notes.reverse() }
      },
      async setAthlete(changes) {
        await athletes.updateOne({ _id: owner }, { $set: { ...changes, updatedAt: new Date() } }, { upsert: true })
      },
      async saveRoom(room) {
        const { messageSequence, ...data } = room
        await rooms.updateOne({ _id: `${owner}:${room.id}` }, { $set: { ...data, owner } }, { upsert: true })
      },
      async rooms() {
        return rooms.find({ owner }, { projection: { _id: 0, owner: 0 } }).sort({ createdAt: -1 }).limit(20).toArray()
      },
      async room(id) {
        return rooms.findOne({ _id: `${owner}:${id}`, owner }, { projection: { _id: 0, owner: 0 } })
      },
      async nativeRoom(spaceId) {
        return rooms.findOne({ owner, mode: 'native', spaceId }, { projection: { _id: 0, owner: 0 } })
      },
      async addRoomMessage(roomId, message) {
        if (await roomMessages.findOne({ _id: `${owner}:${roomId}:${message.id}` })) return
        const room = await rooms.findOneAndUpdate({ _id: `${owner}:${roomId}`, owner }, { $inc: { messageSequence: 1 } }, { returnDocument: 'after' })
        if (!room) throw new Error('Room not found')
        await roomMessages.updateOne({ _id: `${owner}:${roomId}:${message.id}` },
          { $setOnInsert: { ...message, roomId, owner, sequence: room.messageSequence } }, { upsert: true })
      },
      async roomMessages(roomId) {
        return (await roomMessages.find({ owner, roomId }, { projection: { _id: 0, owner: 0 } })
          .sort({ sequence: -1 }).limit(40).toArray()).reverse()
      },
      async roomReply(roomId, replyTo) {
        return roomMessages.findOne({ owner, roomId, replyTo, role: 'ai' }, { projection: { _id: 0, owner: 0 } })
      },
      async note(kind, text, eventId, reportId = null) {
        const _id = `${owner}:${eventId || randomUUID()}`
        await journal.updateOne({ _id }, { $setOnInsert: { owner, kind, text, reportId, createdAt: new Date() } }, { upsert: true })
      },
      async cursor(platform) {
        return (await checkpoints.findOne({ _id: `${owner}:${platform}` }))?.seq ?? null
      },
      async checkpoint(platform, seq) {
        await checkpoints.updateOne({ _id: `${owner}:${platform}` }, { $max: { seq } }, { upsert: true })
      },
      async delivery(messageId) {
        return deliveries.findOne({ _id: `${owner}:${messageId}` })
      },
      async saveDelivery(messageId, reply, kind = 'reply') {
        const _id = `${owner}:${messageId}`
        await deliveries.updateOne({ _id }, { $setOnInsert: { owner, logicalId: messageId, kind, reply, state: 'pending', createdAt: new Date() } }, { upsert: true })
        return deliveries.findOne({ _id })
      },
      async pendingReports() {
        return deliveries.find({ owner, kind: 'report', state: 'pending' }).sort({ createdAt: 1 }).limit(10).toArray()
      },
      async markDelivered(messageId) {
        await deliveries.updateOne({ _id: `${owner}:${messageId}` }, { $set: { state: 'submitted', submittedAt: new Date() } })
      },
      async record(question, reply, channel, contextId) {
        await conversations.insertOne({ owner, question, reply, channel, contextId: contextId || null, createdAt: new Date() })
      },
      async history(contextId) {
        const rows = await conversations.find({ owner, ...(contextId ? { contextId } : {}) }).sort({ createdAt: -1, _id: -1 }).limit(6).toArray()
        return rows.reverse().flatMap(row => [
          { role: 'user', content: row.question },
          { role: 'assistant', content: row.reply },
        ])
      },
      async clearHistory() { await conversations.deleteMany({ owner }) },
      close: () => client.close(),
    }
  } catch {
    await client.close()
    throw new Error('MongoDB connection failed. Start MongoDB or set MONGODB_URI in .env.')
  }
}
