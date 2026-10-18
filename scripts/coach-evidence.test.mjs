import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildCoachEvidence } from '../src/services/coachEvidence.ts'

test('angle evidence aligns phases across different video times and omits missing samples', () => {
  const blank = { leftKneeFlexion: [], rightKneeFlexion: [], hipFlexion: [], shoulderAngleToIce: [] }
  const user = { ...blank, leftKneeFlexion: [{ timestamp: 2.3, angle: 140, frameIndex: 23 }] }
  const reference = { ...blank, leftKneeFlexion: [{ timestamp: 1.2, angle: 122, frameIndex: 12 }] }
  const markers = { user: { takeoffTime: 0.1, landingTime: 2.3 }, reference: { takeoffTime: 0.1, landingTime: 1.2 } }
  const evidence = buildCoachEvidence(user, reference, markers)
  assert.equal(evidence.length, 1)
  assert.equal(evidence[0].phase, 'landing')
  assert.equal(evidence[0].timestamp, 2.3)
  assert.equal(evidence[0].referenceTimestamp, 1.2)
  assert.equal(evidence[0].difference, 18)
  assert.deepEqual(buildCoachEvidence(null, reference, markers), [])
})
