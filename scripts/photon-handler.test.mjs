import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createPhotonHandler } from './photon-handler.mjs'

const message = { id: 'test-message', nativeMessageId: 'photon-native-guid', platform: 'imessage', sentBy: { handle: '+19054629158' }, receivedBy: { id: 'coach' },
  space: { id: 'chat', kind: 'direct' }, content: { type: 'text', text: 'What should I do with my arms?' } }

test('failed sends retry the saved report reply without calling AI again, including after restart', async () => {
  const rows = new Map()
  const sent = []
  let calls = 0
  let fail = true
  const dependencies = {
    allowedSender: '+19054629158',
    delivery: {
      get: async id => rows.get(id),
      save: async (id, reply) => { rows.set(id, { reply, state: 'pending' }); return rows.get(id) },
      submitted: async id => { rows.get(id).state = 'submitted' },
    },
    answer: async (question, channel) => {
      assert.equal(question, message.content.text)
      assert.equal(channel, 'imessage')
      calls++
      return 'Your IMG_5951.mov report at 6–6.6s suggests preserving a soft arm reach.'
    },
    reset: async () => {},
    send: async (body, key) => {
      sent.push({ body, key })
      if (fail) { fail = false; throw new Error('Temporary outage') }
      return { status: 'dispatched' }
    },
  }
  const handle = createPhotonHandler(dependencies)
  await assert.rejects(handle(message), /Temporary outage/)
  const restarted = createPhotonHandler(dependencies)
  await restarted(message)
  await createPhotonHandler(dependencies)(message)
  assert.equal(calls, 1)
  assert.equal(sent.length, 2)
  assert.deepEqual(sent[0], sent[1])
  assert.equal(sent[1].body.senderId, 'coach')
  assert.equal(sent[1].body.replyTo, message.nativeMessageId)
})

test('another sender cannot invoke the coach or send replies', async () => {
  const unexpected = () => { throw new Error('Must not be called') }
  await createPhotonHandler({ allowedSender: 'different', delivery: { get: unexpected }, answer: unexpected, send: unexpected })(message)
})

test('messages addressed to older AI numbers cannot invoke the active coach or change its route', async () => {
  const unexpected = () => { throw new Error('Old number must not be used') }
  await createPhotonHandler({ allowedSender: message.sentBy.handle, agentId: 'new-dedicated-agent',
    memory: { set: unexpected }, delivery: { get: unexpected }, answer: unexpected, send: unexpected })(message)
})

test('START opts in, STOP persists across handler restarts, and other platforms are ignored', async () => {
  const profile = { paused: false, notifications: false }
  const replies = new Map()
  let answers = 0
  let sends = 0
  const dependencies = { allowedSender: message.sentBy.handle, platform: 'imessage',
    memory: { get: async () => profile, set: async changes => Object.assign(profile, changes) },
    delivery: { get: async id => replies.get(id), save: async (id, reply) => { const value = { reply }; replies.set(id, value); return value },
      submitted: async id => { replies.get(id).state = 'submitted' } },
    answer: async () => { answers++; return 'Video-based reply' }, reset: async () => {},
    send: async () => { sends++; return { status: 'dispatched' } },
  }
  const input = (id, text) => ({ ...message, id, content: { type: 'text', text } })
  await createPhotonHandler(dependencies)(input('start', 'START'))
  assert.equal(profile.notifications, true)
  assert.equal(profile.route.platform, 'imessage')
  await createPhotonHandler(dependencies)(input('stop', 'STOP'))
  assert.equal(profile.paused, true)
  assert.equal(profile.notifications, false)
  await createPhotonHandler(dependencies)(input('paused-question', 'How was my spin?'))
  await createPhotonHandler(dependencies)({ ...input('wrong-platform', 'START'), platform: 'sms' })
  assert.equal(answers, 0)
  assert.equal(sends, 2)
  await createPhotonHandler(dependencies)(input('resume', 'START'))
  await createPhotonHandler(dependencies)(input('question', 'How was my spin?'))
  assert.equal(answers, 1)
})
