import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createLibrarySync } from './library-sync.mjs'

test('coach refreshes the library before answers, selects upload order, and refuses stale answers during outages', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'library-coach-'))
  process.env.COACH_DATA_DIR = directory
  const state = await import('./coach-state.mjs')
  const rows = new Map(), conversations = []
  const ordered = () => [...rows.values()].sort((a, b) => a.savedAt.localeCompare(b.savedAt))
  const database = {
    saveHostedAnalysis: async row => { rows.set(row.sourceId, { ...row, id: row.sourceId }) },
    list: async () => ordered(),
    latestFeedback: async () => ordered().at(-1),
    history: async context => { conversations.push(context); return [] },
    record: async () => {}, close: async () => {},
  }
  const videos = [
    { analysis_id: 'old', filename: 'old.mov', uploaded_at: 100, status: 'done' },
    { analysis_id: 'new', filename: 'new.mov', uploaded_at: 200, status: 'done' },
  ]
  let offline = false
  const sync = createLibrarySync({ baseUrl: 'https://api.example',
    importedIds: async () => [...rows.keys()], saveReport: state.saveMessagingAnalysis,
    fetchImpl: async url => {
      if (offline) throw new Error('offline')
      const id = url.split('/').at(-1)
      return { ok: true, json: async () => id === 'history' ? { videos } :
        { analysis_id: id, status: 'done', message: `Report for ${id}` } }
    } })
  const originalFetch = globalThis.fetch
  let expected = 'new.mov', modelCalls = 0
  globalThis.fetch = async (url, options) => {
    assert.match(String(url), /api.openai.com/)
    const instructions = JSON.parse(options.body).instructions
    const latest = JSON.parse(instructions.split('Latest coaching feedback (JSON): ')[1].split('\n')[0])
    assert.equal(latest.videoName, expected)
    assert.match(instructions, /upload time rather than import or completion time/)
    modelCalls++
    return { ok: true, json: async () => ({ output: [{ content: [{ type: 'output_text', text: 'Use the latest report.' }] }] }) }
  }
  const server = await state.startCoachServer(0, { database, librarySync: sync })
  try {
    assert.equal(await state.respondWithCoach('How was my jump?', 'imessage'), 'Use the latest report.')
    assert.equal(rows.size, 2)
    videos.push({ analysis_id: 'third', filename: 'third.mov', uploaded_at: 300, status: 'done' })
    expected = 'third.mov'
    await state.respondWithCoach('What should I practice?', 'imessage')
    assert.equal(rows.size, 3)
    assert.equal(conversations.at(-1), 'agent-third', 'conversation context changes with the default upload')
    videos.push({ analysis_id: 'late', filename: 'late.mov', uploaded_at: 150, status: 'done' })
    await state.respondWithCoach('And now?', 'imessage')
    assert.equal(rows.size, 4, 'older uploads are retained without replacing the newest report')
    offline = true
    assert.match(await state.respondWithCoach('How was it?', 'imessage'), /could not refresh/)
    assert.equal(modelCalls, 3, 'an outage must not produce an answer from stale evidence')
  } finally {
    globalThis.fetch = originalFetch
    await new Promise(resolve => server.close(resolve))
    await sync.stop()
    await rm(directory, { recursive: true, force: true })
  }
})
