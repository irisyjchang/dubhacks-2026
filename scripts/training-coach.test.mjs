import { test } from 'node:test'
import assert from 'node:assert/strict'
import { trainingCommand, reportNotification, smsText } from './training-coach.mjs'

const feedback = { id: 'report1', videoName: 'spin.mov', savedAt: '2026-10-17T20:00:00Z',
  feedback: { report: 'At 6-6.6s preserve a soft arm reach.', headline: 'Review arm consistency.', findings: [{ kind: 'review', action: 'Review your reach at 6s.' }] } }

test('goal and human coach notes become durable memory; practice is not measured improvement', async () => {
  const profile = {}
  const notes = new Map()
  const database = { setAthlete: async changes => Object.assign(profile, changes),
    note: async (kind, text, id) => notes.set(id, { kind, text }) }
  const options = { database, feedback, eventId: 'goal-message' }
  await trainingCommand('My goal is a consistent arm reach', options)
  await trainingCommand('My goal is a consistent arm reach', options)
  assert.equal(profile.goal, 'a consistent arm reach')
  assert.equal(notes.size, 1)
  await trainingCommand('My coach said preserve the forward reach', { ...options, eventId: 'coach-message' })
  assert.equal(notes.get('coach-message').kind, 'coach')
  const reply = await trainingCommand('I practiced five slow entries', { ...options, eventId: 'practice-message' })
  assert.match(reply, /not a measured performance change/)
  assert.equal(notes.get('practice-message').kind, 'done')
})

test('practice plan synthesizes two independent role reviews and survives one unavailable reviewer', async () => {
  const calls = []
  const complete = async (messages, instructions) => {
    calls.push(messages[0].content)
    assert.equal(instructions, 'verified evidence')
    if (messages[0].content.includes('As the evidence reviewer')) return 'Supported soft reach at 6s; no extra extension supported.'
    if (messages[0].content.includes('As the practice planner')) throw new Error('temporarily unavailable')
    assert.match(messages[0].content, /Supported soft reach at 6s/)
    assert.match(messages[0].content, /Unavailable; use original evidence only/)
    return 'Keep the soft reach; review a matching view. Text DONE after practice.'
  }
  const reply = await trainingCommand('PLAN', { feedback, complete, instructions: 'verified evidence' })
  assert.equal(calls.length, 3)
  assert.match(reply, /DONE/)
})

test('one attempt cannot establish improvement, and report follow-ups retain the user goal', async () => {
  const reply = await trainingCommand('PROGRESS', { database: { recentFeedback: async () => [feedback] }, feedback })
  assert.match(reply, /need another attempt/)
  const notification = reportNotification(feedback, { goal: 'Maintain my forward reach' })
  assert.match(notification, /spin.mov/)
  assert.match(notification, /Maintain my forward reach/)
  assert.match(notification, /PLAN/)
  assert.ok(smsText('A long response. '.repeat(300)).length <= 1100)
})
