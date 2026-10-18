import { acknowledgementReaction } from './coach-reactions.mjs'
import { randomUUID } from 'node:crypto'

export function addressedToAI(text) {
  return /^(?:plan|progress|latest|help|timeline|share)\s*[?!.]*$/i.test(text.trim()) || /^(?:@?coach\s*ai\b[:,]?|@?ai\b[:,]?|\/(?:ai|plan|progress|latest|help|timeline|share)\b)/i.test(text.trim())
}

export function createGroupCoach({ database, respond }) {
  let queue = Promise.resolve()
  const enqueue = work => {
    const task = queue.catch(() => {}).then(work)
    queue = task
    return task
  }
  return {
    async createPreview(name = 'Skating group + AI') {
      const room = { id: randomUUID(), name: String(name).slice(0, 80), mode: 'preview',
        muted: false, createdAt: new Date().toISOString() }
      await database.saveRoom(room)
      return room
    },
    list: () => database.rooms(),
    async view(id) {
      const room = await database.room(id)
      if (!room) return null
      return { ...room, decision: null,
        members: room.members?.map(member => ({ ...member, role: member.role === 'ai' ? 'ai' : 'member' })),
        messages: (await database.roomMessages(id)).map(message => ({ ...message, role: message.role === 'ai' ? 'ai' : 'member' })) }
    },
    async bindNative(spaceId, members, platform) {
      const existing = await database.nativeRoom(spaceId)
      if (existing) {
        if (existing.decision || JSON.stringify(existing.members) !== JSON.stringify(members)) {
          existing.members = members
          existing.decision = null
          await database.saveRoom(existing)
        }
        return existing
      }
      const room = { id: randomUUID(), name: 'Skating group + AI', mode: 'native',
        spaceId, platform, members, muted: false, createdAt: new Date().toISOString() }
      await database.saveRoom(room)
      return room
    },
    post(roomId, input) {
      return enqueue(async () => {
        const room = await database.room(roomId)
        if (!room) throw new Error('Room not found')
        if (input.role !== 'member' || typeof input.text !== 'string' || !input.text.trim() || input.text.length > 3000) {
          throw new Error('Invalid participant or message')
        }
        if (typeof input.id !== 'string' || !/^[a-zA-Z0-9_-]{1,128}$/.test(input.id)) throw new Error('Invalid message ID')
        const previous = await database.roomMessages(room.id)
        const old = previous.find(message => message.id === input.id)
        const text = input.text.trim()
        if (old && (old.role === 'ai' || old.text !== text || (old.participantId && old.participantId !== input.participantId))) throw new Error('Message ID already used')
        const priorReply = await database.roomReply(room.id, input.id)
        if (priorReply) return { roomId, reply: priorReply.text, replied: true, replay: true }
        if (!old) await database.addRoomMessage(room.id, { id: input.id, role: input.role, text, participantId: input.participantId,
          createdAt: input.createdAt || new Date().toISOString() })
        const command = text.replace(/^\//, '').toLowerCase()
        if (['mute ai', 'mute', 'stop'].includes(command)) {
          room.muted = true
          await database.saveRoom(room)
          return { roomId, replied: false }
        }
        if (['unmute ai', 'unmute', 'start'].includes(command)) {
          room.muted = false
          await database.saveRoom(room)
          return { roomId, replied: false }
        }
        const last = previous.filter(message => message.id !== input.id).at(-1)
        const reaction = acknowledgementReaction(text)
        const recentAI = last?.role === 'ai' && Date.now() - Date.parse(last.createdAt) < 120000
        if (!room.muted && reaction && (addressedToAI(text) || recentAI)) {
          return { roomId, replied: false, reaction }
        }
        const answeringAI = last?.role === 'ai' && last.text.trim().endsWith('?') &&
          Date.now() - Date.parse(last.createdAt) < 120000 && /^(yes|no|please|sure|okay|ok|go ahead)[.!\s]*$/i.test(text)
        if (room.muted || (!addressedToAI(text) && !answeringAI)) return { roomId, replied: false }
        const question = text.replace(/^(?:@?coach\s*ai\b[:,]?|@?ai\b[:,]?|\/ai\b)\s*/i, '').trim().replace(/^\/(plan|progress|latest|help|timeline|share)\b/i, '$1').replace(/^(plan|progress|latest|help|timeline|share)[?!.]*$/i, '$1') || 'Help us review this skating attempt.'
        const transcript = await database.roomMessages(room.id)
        const reply = /^help[?!.]*$/i.test(question)
          ? 'Group coach: text AI, followed by your question, or PLAN, PROGRESS, LATEST, TIMELINE, or SHARE. MUTE AI pauses this group; UNMUTE AI resumes it. Send GOAL, DONE, COACH, CHECKIN directly to the AI line for personal features. Typing indicators appear while preparing group answers.'
          : await (input.withActivity || (work => work()))(() => respond(question, room.mode === 'native' ? `${room.platform}-group` : 'group-preview', input.id, {
          roomId: room.id, speaker: 'member', speakerId: input.participantId,
          transcript: transcript.slice(-16).map(({ role, text, participantId }) => ({ role: role === 'ai' ? 'ai' : 'member', text, participantId })),
        }))
        await database.addRoomMessage(room.id, { id: `ai-${input.id}`, role: 'ai', text: reply,
          replyTo: input.id, createdAt: new Date().toISOString() })
        return { roomId, reply, replied: true }
      })
    },
  }
}
