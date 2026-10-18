import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { analysisId } from './coach-database.mjs'

test('new-report follow-ups require opt-in, deduplicate, persist while unavailable, and respect STOP', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'coach-notify-'))
  process.env.COACH_DATA_DIR = directory
  const { startCoachServer, setTextTransport, flushReportNotifications } = await import('./coach-state.mjs')
  const profile = { notifications: false, paused: false, goal: 'Soft forward reach',
    route: { platform: 'imessage', senderId: 'our-agent', spaceId: 'our-user-chat' } }
  const reports = new Map()
  const deliveries = new Map()
  const sent = []
  let ready = true
  let agentId = 'our-agent'
  const database = {
    save: async value => {
      const id = analysisId(value)
      const inserted = !reports.has(id)
      reports.set(id, { ...value, id })
      return { ...value, id, inserted }
    },
    list: async () => [...reports.values()], athlete: async () => profile,
    saveDelivery: async (logicalId, reply, kind) => {
      if (!deliveries.has(logicalId)) deliveries.set(logicalId, { logicalId, reply, kind, state: 'pending' })
      return deliveries.get(logicalId)
    },
    pendingReports: async () => [...deliveries.values()].filter(row => row.state === 'pending'),
    markDelivered: async id => { deliveries.get(id).state = 'submitted' }, close: async () => {},
  }
  const server = await startCoachServer(0, { database })
  setTextTransport({ status: () => ({ ready, channel: 'imessage', agentId }), send: async (body, key) => {
    assert.equal(body.spaceId, 'our-user-chat')
    assert.equal(body.senderId, 'our-agent')
    sent.push({ body, key })
    return { status: 'dispatched' }
  } })
  async function upload(sourceId) {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/api/coach/analysis`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: 'spincoach', sourceId, videoName: `${sourceId}.mov`,
        feedback: { report: 'Preserve your soft reach at 6s.', headline: 'Review arm consistency.' } }),
    })
    assert.equal(response.status, 200)
  }
  try {
    await upload('before-opt-in')
    assert.equal(sent.length, 0)
    profile.notifications = true
    await upload('after-opt-in')
    await flushReportNotifications()
    assert.equal(sent.length, 1)
    assert.match(sent[0].body.content.text, /Soft forward reach/)
    await upload('after-opt-in')
    await flushReportNotifications()
    assert.equal(sent.length, 1)
    ready = false
    await upload('queued')
    assert.equal(sent.length, 1)
    profile.paused = true
    ready = true
    await flushReportNotifications()
    assert.equal(sent.length, 1)
    profile.paused = false
    await flushReportNotifications()
    assert.equal(sent.length, 2)
    agentId = 'new-dedicated-agent'
    await upload('after-number-switch')
    await flushReportNotifications()
    assert.equal(sent.length, 2, 'old saved routes must not send from the previous AI number')
    await flushReportNotifications()
    assert.equal(sent.length, 2)
  } finally {
    setTextTransport(null)
    await new Promise(resolve => server.close(resolve))
    await rm(directory, { recursive: true, force: true })
  }
})
