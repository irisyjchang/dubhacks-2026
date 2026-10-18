import { createHash } from 'node:crypto'

export function canonicalHandle(value) {
  if (typeof value !== 'string') return ''
  if (/^[\d+().\s-]+$/.test(value)) {
    const digits = value.replace(/\D/g, '')
    return digits.length === 10 ? `+1${digits}` : `+${digits}`
  }
  return value.toLowerCase()
}

export function stableId(value) {
  return createHash('sha256').update(value).digest('hex')
}

export function normalizeSpectrumMessage(space, message, number, agentId) {
  if (message.platform !== 'imessage' || message.direction !== 'inbound' ||
      canonicalHandle(space.phone) !== number || !['text', 'attachment', 'group', 'reply'].includes(message.content?.type) ||
      !['dm', 'group'].includes(space.type) || !message.id || !space.id) return null
  const handle = canonicalHandle(message.sender?.address || message.sender?.id)
  if (!handle || handle === number) return null
  const timestamp = new Date(message.timestamp)
  if (!Number.isFinite(timestamp.getTime())) return null
  const nativeId = /^p:\d+\/(.+)$/.exec(message.id)?.[1] || message.id
  const texts = content => {
    if (content?.type === 'text') return content.text || ''
    if (content?.type === 'reply') return texts(content.content)
    if (content?.type === 'group') return (content.items || []).map(item => texts(item.content || item)).filter(Boolean).join('\n')
    return ''
  }
  const text = texts(message.content)
  return {
    id: `sp-${stableId(`${number}:${space.id}:${nativeId}`)}`,
    nativeMessageId: nativeId,
    platform: 'imessage', sentBy: { id: handle, handle }, receivedBy: { id: agentId },
    space: { id: space.id, kind: space.type === 'group' ? 'group' : 'direct' },
    content: { type: text ? 'text' : 'attachment', text }, createdAt: timestamp.toISOString(),
  }
}

export function spectrumMembers(participants, number, agentId) {
  const humans = participants.map(person => canonicalHandle(person.address || person.id)).filter(handle => handle !== number)
  if (humans.some(handle => !handle) || new Set(humans).size !== humans.length) return []
  return [...humans.map(handle => ({ id: handle, handle, kind: 'human' })), { id: agentId, handle: number, kind: 'agent' }]
}

export function assertCoachChat(chat, { spaceId, number, student }) {
  const refuse = message => { const error = new Error(message); error.code = 'COACH_CHAT_NOT_AUTHORIZED'; throw error }
  if (chat.guid !== spaceId) refuse('Unexpected conversation')
  const participants = spectrumMembers(chat.participants, number, 'agent').filter(person => person.kind === 'human')
  const handles = participants.map(person => person.handle)
  if (chat.isGroup ? !handles.includes(student)
    : handles.length !== 1 || handles[0] !== student) {
    refuse('Conversation does not include the owner of the shared video feedback')
  }
}
