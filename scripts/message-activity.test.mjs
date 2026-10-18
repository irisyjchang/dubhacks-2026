import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createMessageActivity } from './message-activity.mjs'

const message = { space: { id: 'chat' } }
test('read and typing bracket model work and clear typing on failure', async () => {
  for (const fail of [false, true]) {
    const events = []
    const activity = createMessageActivity({ authorize: async id => { assert.equal(id, 'chat'); events.push('authorized') },
      chats: { markRead: async () => events.push('read'), setTyping: async (_id, value) => events.push(value) } })
    const result = activity(message, async () => { events.push('model'); if (fail) throw new Error('model failed'); return 'answer' })
    if (fail) await assert.rejects(result, /model failed/)
    else assert.equal(await result, 'answer')
    assert.deepEqual(events, ['authorized', 'read', true, 'model', false])
  }
})
test('unauthorized chat never receives presence or invokes model', async () => {
  const unexpected = async () => assert.fail('unauthorized action')
  const activity = createMessageActivity({ authorize: async () => { throw new Error('denied') },
    chats: { markRead: unexpected, setTyping: unexpected } })
  await assert.rejects(activity(message, unexpected), /denied/)
})
test('presence outages do not prevent coaching', async () => {
  const unavailable = async () => { throw new Error('presence unavailable') }
  const activity = createMessageActivity({ authorize: async () => {}, chats: { markRead: unavailable, setTyping: unavailable } })
  assert.equal(await activity(message, async () => 'answer'), 'answer')
})
