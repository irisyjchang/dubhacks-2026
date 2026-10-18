import { test } from 'node:test'
import assert from 'node:assert/strict'
import { MongoClient } from 'mongodb'
import { analysisId, timelineFilter } from './coach-database.mjs'

test('timeline cursor preserves owner scope and orders equal-time reports without overlap', () => {
  const time = '2026-10-17T20:17:47.063Z'
  const id = 'a'.repeat(64)
  const cursor = Buffer.from(JSON.stringify([time, id])).toString('base64url')
  const filter = timelineFilter('athlete', cursor)
  assert.equal(filter.owner, 'athlete')
  assert.equal(filter.source, 'spincoach')
  assert.deepEqual(filter.$or, [{ savedAt: { $lt: time } }, { savedAt: time, _id: { $lt: `athlete:${id}` } }])
  assert.throws(() => timelineFilter('athlete', Buffer.from('{"owner":"someone-else"}').toString('base64url')), /Invalid timeline cursor/)
})

test('analysis identity ignores save time and changes with measured results', () => {
  const first = { videoName: 'jump.mp4', metrics: { airTime: 0.5 }, savedAt: 'first' }
  assert.equal(analysisId(first), analysisId({ ...first, savedAt: 'second' }))
  assert.notEqual(analysisId(first), analysisId({ ...first, metrics: { airTime: 0.7 } }))
})

test('configured MongoDB is reachable (read-only)', { skip: !process.env.MONGODB_URI }, async () => {
  const client = new MongoClient(process.env.MONGODB_URI, { serverSelectionTimeoutMS: 5000 })
  try {
    await client.connect()
    const result = await client.db(process.env.MONGODB_DB || 'figure_skating_coach').command({ ping: 1 })
    assert.equal(result.ok, 1)
  } finally { await client.close() }
})
