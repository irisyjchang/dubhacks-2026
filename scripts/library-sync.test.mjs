import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createLibrarySync } from './library-sync.mjs'

const video = (id, time, status = 'done') => ({ analysis_id: id, filename: `${id}.mov`, uploaded_at: time, status })
function fixture(videos) {
  const rows = new Map(), calls = []
  let unavailable = false
  const dependencies = {
    baseUrl: 'https://api.example',
    importedIds: async () => [...rows.keys()].map(id => `agent-${id}`),
    saveReport: async report => { rows.set(report.analysisId, report) },
    fetchImpl: async url => {
      calls.push(url)
      if (unavailable) throw new Error('offline')
      const id = url.split('/').at(-1)
      return { ok: true, json: async () => id === 'history' ? { videos } :
        { analysis_id: id, status: 'done', message: `Feedback for ${id}` } }
    },
  }
  return { dependencies, rows, calls, offline: () => { unavailable = true } }
}

test('backfills all completed uploads by upload time, skips processing/failed and persists deduplication', async () => {
  const f = fixture([video('old', 100), video('failed', 400, 'failed'), video('new', 200), video('pending', 300, 'processing')])
  const sync = createLibrarySync(f.dependencies)
  const first = sync.sync()
  assert.equal(sync.sync(), first, 'concurrent refreshes share a single import')
  assert.equal((await first).imported, 2)
  assert.deepEqual([...f.rows.keys()], ['new', 'old'])
  assert.equal(f.rows.get('old').uploadedAt, '1970-01-01T00:01:40.000Z')
  assert.equal(f.rows.get('new').libraryImported, true)
  const restarted = createLibrarySync(f.dependencies)
  assert.equal((await restarted.sync()).imported, 0)
  assert.equal(f.calls.filter(url => url.includes('/agent/analysis/')).length, 2)
  await sync.stop()
  await restarted.stop()
})

test('new uploads and newly completed jobs are imported on the next refresh', async () => {
  const videos = [video('first', 100), video('next', 200, 'processing')]
  const f = fixture(videos)
  const sync = createLibrarySync(f.dependencies)
  await sync.sync()
  videos[1].status = 'done'
  videos.push(video('latest', 300))
  assert.equal((await sync.sync()).imported, 2)
  assert.equal(f.rows.size, 3)
  await sync.stop()
})

test('outages and invalid or mismatched reports do not become coach memory', async () => {
  const f = fixture([video('one', 100)])
  f.offline()
  await assert.rejects(createLibrarySync(f.dependencies).sync(), /offline/)
  for (const report of [ { analysis_id: 'other', status: 'done', message: 'wrong' },
    { analysis_id: 'one', status: 'processing' }, { analysis_id: 'one', status: 'done', message: '' } ]) {
    const sync = createLibrarySync({ ...f.dependencies, fetchImpl: async url => ({ ok: true,
      json: async () => url.endsWith('/history') ? { videos: [video('one', 100)] } : report }) })
    await assert.rejects(sync.sync(), /could not be imported/)
    assert.equal(f.rows.size, 0)
    await sync.stop()
  }
})

test('unavailable older reports remain in the catalog and are retried without blocking the latest video', async () => {
  const f = fixture([video('old', 100), video('new', 200)])
  const fetchImpl = f.dependencies.fetchImpl
  let manifest
  const sync = createLibrarySync({ ...f.dependencies, saveManifest: async uploads => { manifest = uploads },
    fetchImpl: async url => url.endsWith('/old') ? { ok: false, status: 500 } : fetchImpl(url) })
  const result = await sync.sync()
  assert.equal(result.imported, 1)
  assert.deepEqual(result.unavailableReports, ['old'])
  assert.equal(manifest.find(upload => upload.analysisId === 'old').reportAvailable, false)
  assert.equal(manifest.find(upload => upload.analysisId === 'new').reportAvailable, true)
  assert.deepEqual((await sync.sync()).unavailableReports, ['old'])
  await sync.stop()
})

test('bad history is rejected before importing reports', async () => {
  for (const entry of [video('../escape', 100), video('bad', NaN), { status: 'done', uploaded_at: 100 }]) {
    const f = fixture([entry])
    await assert.rejects(createLibrarySync(f.dependencies).sync(), /Invalid library entry/)
    assert.equal(f.rows.size, 0)
  }
})
