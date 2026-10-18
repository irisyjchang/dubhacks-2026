import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createGroupCoach } from './group-coach.mjs'
import { createNativeGroupHandler } from './photon-group-handler.mjs'

function store() {
  const rooms = new Map(), messages = new Map()
  return {
    saveRoom: async room => rooms.set(room.id, structuredClone(room)),
    room: async id => structuredClone(rooms.get(id)),
    rooms: async () => [...rooms.values()],
    nativeRoom: async id => [...rooms.values()].find(room => room.spaceId === id),
    addRoomMessage: async (id, message) => { const list = messages.get(id) || []; if (!list.some(old => old.id === message.id)) list.push(message); messages.set(id, list) },
    roomMessages: async id => messages.get(id) || [],
    roomReply: async (id, replyTo) => (messages.get(id) || []).find(message => message.role === 'ai' && message.replyTo === replyTo),
  }
}

test('all members can invite the AI, follow up, and mute without role or approval rules', async () => {
  const database = store(), calls = []
  const group = createGroupCoach({ database, respond: async (...args) => { calls.push(args); return 'Review the reach at 6s. Want a drill?' } })
  const room = await group.createPreview()
  const post = (id, participantId, text) => group.post(room.id, { id, role: 'member', participantId, text })
  assert.equal((await post('human-chat', 'alice', 'How did that look?')).replied, false)
  await post('approval', 'bob', 'APPROVE')
  await post('revision', 'alice', 'REVISE preserve the reach')
  assert.equal((await group.view(room.id)).decision, null)
  await post('invite', 'bob', 'AI, what should we focus on?')
  assert.equal(calls[0][3].speaker, 'member')
  assert.equal(calls[0][3].speakerId, 'bob')
  assert.equal(calls[0][3].decision, undefined)
  assert.ok(calls[0][3].transcript.every(message => message.role === 'member'))
  await post('invite', 'bob', 'AI, what should we focus on?')
  assert.equal(calls.length, 1)
  await assert.rejects(post('invite', 'alice', 'AI, what should we focus on?'), /already used/)
  await post('follow-up', 'alice', 'yes')
  assert.equal(calls.length, 2, 'any member may answer the AI follow-up')
  await post('mute', 'bob', 'STOP')
  assert.equal((await post('muted-invite', 'alice', 'AI, help')).replied, false)
  await post('unmute', 'alice', 'START')
  await post('new-invite', 'alice', '/ai explain the cue')
  assert.equal(calls.at(-1)[0], 'explain the cue')
})

test('native room refreshes current members and removes legacy decisions', async () => {
  const database = store()
  const group = createGroupCoach({ database, respond: async () => 'Feedback' })
  const room = await group.bindNative('chat', [{ id: 'old-coach', role: 'coach' }], 'imessage')
  await database.saveRoom({ ...room, decision: { status: 'approved' } })
  const updated = await group.bindNative('chat', [{ id: 'alice', role: 'member' }], 'imessage')
  assert.equal(updated.id, room.id)
  assert.equal(updated.decision, null)
  assert.equal(updated.members[0].role, 'member')
})

test('any current participant can invoke native AI and send retries reuse a saved reply', async () => {
  const owner = { id: 'owner', kind: 'human', handle: '+19054629158' }
  const bob = { id: 'bob', kind: 'human', handle: 'bob@example.com' }
  const agent = { id: 'agent', kind: 'agent' }
  let roster = [owner, bob, agent], calls = 0, fail = true, capable = true
  const rows = new Map(), sent = []
  const dependencies = { studentHandle: owner.handle, agentId: agent.id, groupCapable: () => capable,
    members: async () => roster,
    delivery: { get: async id => rows.get(id), save: async (id, reply) => { const value = { reply }; rows.set(id, value); return value }, submitted: async id => { rows.get(id).state = 'submitted' } },
    groups: { native: async (_message, members) => { calls++; assert.equal(members.find(member => member.id === bob.id).role, 'member'); return { replied: true, reply: 'The saved report at 6s suggests a soft reach.' } } },
    send: async (body, key) => { sent.push({ body, key }); if (fail) { fail = false; throw new Error('Offline') } return { status: 'submitted' } } }
  const input = { id: 'invite', platform: 'imessage', space: { id: 'chat', kind: 'group' }, sentBy: bob, content: { type: 'text', text: 'AI, help' } }
  await assert.rejects(createNativeGroupHandler(dependencies)(input), /Offline/)
  await createNativeGroupHandler(dependencies)(input)
  await createNativeGroupHandler(dependencies)(input)
  assert.equal(calls, 1)
  assert.deepEqual(sent[0], sent[1])
  roster = [owner, bob, { id: 'new-member', kind: 'human', handle: 'new@example.com' }, agent]
  await createNativeGroupHandler(dependencies)({ ...input, id: 'new-invite' })
  assert.equal(calls, 2, 'adding a person must not silence the group')
  await createNativeGroupHandler(dependencies)({ ...input, id: 'forged', sentBy: { ...bob, id: 'not-in-chat' } })
  assert.equal(calls, 2, 'a sender must actually belong to the current group')
  roster = [bob, agent]
  await createNativeGroupHandler(dependencies)({ ...input, id: 'no-owner' })
  assert.equal(calls, 2, 'unrelated groups do not receive the owner video feedback')
  roster = [owner, bob, agent]; capable = false
  await createNativeGroupHandler(dependencies)({ ...input, id: 'not-ready' })
  assert.equal(calls, 2)
})

test('plain group commands invoke AI and HELP explains group scope', async () => {
  const calls = []
  const group = createGroupCoach({ database: store(), respond: async question => { calls.push(question); return 'Shared feedback' } })
  const room = await group.createPreview()
  const post = (id, text) => group.post(room.id, { id, text, role: 'member', participantId: 'alice' })
  for (const text of ['PLAN', 'PROGRESS', 'LATEST', '/plan']) {
    assert.equal((await post(`command-${calls.length}`, text)).replied, true)
  }
  const help = await post('help', 'HELP')
  assert.match(help.reply, /directly to the AI line/)
  assert.equal(calls.length, 4)
  assert.equal((await post('personal', 'GOAL better reach')).replied, false)
  assert.equal((await post('ordinary', 'plan a trip')).replied, false)
  await post('mute', 'MUTE AI')
  assert.equal((await post('muted', 'PLAN')).replied, false)
})

test('group activity wraps answers but excludes human chat, muted requests, and replays', async () => {
  const events = []
  const group = createGroupCoach({ database: store(), respond: async () => { events.push('answer'); return 'Practice cue' } })
  const room = await group.createPreview()
  const post = (id, text) => group.post(room.id, { id, text, role: 'member', participantId: 'alice',
    withActivity: async work => { events.push('typing'); try { return await work() } finally { events.push('clear') } } })
  await post('ordinary', 'How was your day?')
  assert.deepEqual(events, [])
  await post('plan', 'PLAN')
  assert.deepEqual(events, ['typing', 'answer', 'clear'])
  await post('plan', 'PLAN')
  await post('mute', 'STOP')
  await post('muted-plan', 'PLAN')
  assert.deepEqual(events, ['typing', 'answer', 'clear'])
})

test('group thanks reacts only to recent AI or explicit address and respects mute', async () => {
  const group = createGroupCoach({ database: store(), respond: async () => 'Try the cue.' })
  const room = await group.createPreview()
  const post = (id, text) => group.post(room.id, { id, text, role: 'member', participantId: 'alice' })
  assert.equal((await post('human-thanks', 'thanks')).reaction, undefined)
  await post('question', 'AI, help')
  assert.deepEqual((await post('thanks', 'thanks, that helped!')).reaction, { kind: 'like' })
  await post('mute', 'STOP')
  assert.equal((await post('muted', 'AI, thanks')).reaction, undefined)
})
