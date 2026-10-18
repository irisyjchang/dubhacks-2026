import { test } from 'node:test'
import assert from 'node:assert/strict'
import { canonicalHandle, normalizeSpectrumMessage, spectrumMembers, assertCoachChat } from './spectrum-adapter.mjs'

const number = '+16285027257', student = '+19054629158', coach = '+12062457436', agentId = `spectrum:${number}`
const space = { phone: number, id: 'iMessage;+;test-chat', type: 'group' }
const message = { id: 'original-message-guid', platform: 'imessage', direction: 'inbound',
  sender: { id: student }, timestamp: new Date('2026-10-17T20:00:00Z'), content: { type: 'text', text: 'AI, review my arms' } }

test('Spectrum normalization pins the configured line and ignores outbound echoes', () => {
  assert.equal(canonicalHandle('(206) 245-7436'), coach)
  const result = normalizeSpectrumMessage(space, message, number, agentId)
  assert.equal(result.nativeMessageId, message.id)
  assert.equal(result.sentBy.id, student)
  assert.equal(result.receivedBy.id, agentId)
  assert.equal(result.space.kind, 'group')
  assert.equal(result.createdAt, message.timestamp.toISOString())
  assert.match(result.id, /^sp-[a-f0-9]{64}$/)
  assert.deepEqual(normalizeSpectrumMessage(space, message, number, agentId), result)
  assert.equal(normalizeSpectrumMessage({ ...space, phone: '+15555555555' }, message, number, agentId), null)
  assert.equal(normalizeSpectrumMessage(space, { ...message, direction: 'outbound' }, number, agentId), null)
  assert.equal(normalizeSpectrumMessage(space, { ...message, direction: undefined }, number, agentId), null)
  assert.equal(normalizeSpectrumMessage(space, { ...message, sender: { id: number } }, number, agentId), null)
  assert.equal(normalizeSpectrumMessage(space, { ...message, timestamp: 'invalid' }, number, agentId), null)
})

test('Spectrum roster maps exact coach/student roles without counting the agent twice', () => {
  const participants = [{ address: student }, { address: coach }, { address: number }]
  const members = spectrumMembers(participants, number, agentId)
  assert.equal(members.length, 3)
  assert.equal(members[2].kind, 'agent')
  assert.equal(members[2].id, agentId)
  assert.deepEqual(spectrumMembers([{ address: student }, { address: student }], number, agentId), [])
})

test('group feedback follows current membership without coach or guest permissions', () => {
  const options = { spaceId: space.id, number, student }
  const chat = { guid: space.id, isGroup: true, participants: [{ address: student }, { address: 'anyone@example.com' }] }
  assert.doesNotThrow(() => assertCoachChat(chat, options))
  assert.doesNotThrow(() => assertCoachChat({ ...chat, participants: [...chat.participants, { address: '+15555555555' }] }, options))
  assert.throws(() => assertCoachChat({ ...chat, guid: 'another-chat' }, options), /Unexpected conversation/)
  assert.throws(() => assertCoachChat({ ...chat, participants: [{ address: 'unrelated@example.com' }] }, options), /owner/)
  assert.doesNotThrow(() => assertCoachChat({ ...chat, isGroup: false, participants: [{ address: student }] }, options))
  assert.throws(() => assertCoachChat({ ...chat, isGroup: false, participants: [{ address: 'anyone@example.com' }] }, options), /owner/)
  assert.throws(() => assertCoachChat({ ...chat, participants: [] }, options), /owner/)
})

test('video and caption events use the canonical parent ID for deduplication', () => {
  const video = normalizeSpectrumMessage(space, { ...message, content: { type: 'attachment' } }, number, agentId)
  assert.equal(video.content.type, 'attachment')
  assert.equal(video.nativeMessageId, message.id)
  const caption = normalizeSpectrumMessage(space, { ...message, id: `p:0/${message.id}` }, number, agentId)
  assert.equal(video.id, caption.id)
  const combined = normalizeSpectrumMessage(space, { ...message, content: { type: 'group', items: [
    { content: { type: 'attachment' } }, { content: { type: 'text', text: 'Review my landing' } },
  ] } }, number, agentId)
  assert.equal(combined.content.text, 'Review my landing')
})


test('reset cutoff ignores old and replayed messages while allowing new messages', () => {
  const cutoff = message.timestamp.getTime()
  assert.equal(normalizeSpectrumMessage(space, message, number, agentId, cutoff), null)
  assert.equal(normalizeSpectrumMessage(space, { ...message, timestamp: new Date(cutoff - 1000) }, number, agentId, cutoff), null)
  assert.ok(normalizeSpectrumMessage(space, { ...message, timestamp: new Date(cutoff + 1) }, number, agentId, cutoff))
})
