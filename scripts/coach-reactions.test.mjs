import { test } from 'node:test'
import assert from 'node:assert/strict'
import { acknowledgementReaction } from './coach-reactions.mjs'
import { createPhotonHandler } from './photon-handler.mjs'
test('acknowledges thanks and explicit resolution without celebrating unresolved questions', () => {
  for (const text of ['thanks!', 'AI, thanks, that helped', 'that fixed it', 'thank you so much']) assert.deepEqual(acknowledgementReaction(text), { kind: 'like' })
  for (const text of ['thanks but it still hurts', 'that worked?', 'not fixed', 'thanks, what next?']) assert.equal(acknowledgementReaction(text), null)
})
test('DM thanks reacts once, skips model, and respects durable STOP', async () => {
  let paused = false, reactions = 0
  const unexpected = async () => assert.fail('must not generate a reply')
  const handle = createPhotonHandler({ allowedSender: 'owner', agentId: 'agent',
    memory: { set: async () => {}, get: async () => ({ paused }) }, delivery: { get: async () => null },
    answer: unexpected, send: unexpected, react: async () => { reactions++ } })
  const message = { id: 'thanks', nativeMessageId: 'guid', platform: 'imessage', sentBy: { handle: 'owner' },
    receivedBy: { id: 'agent' }, space: { id: 'chat', kind: 'direct' }, content: { type: 'text', text: 'thanks, that helped!' } }
  await handle(message)
  await handle(message)
  paused = true
  await handle({ ...message, id: 'paused' })
  assert.equal(reactions, 1)
})
