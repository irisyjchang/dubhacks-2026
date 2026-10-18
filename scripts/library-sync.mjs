// The web library and Photon share the hosted analysis API, not the website URL.
export function createLibrarySync({ baseUrl, importedIds, saveReport, saveManifest = async () => {}, fetchImpl = fetch }) {
  const base = new URL(baseUrl)
  if (base.protocol !== 'https:' || base.username || base.password || base.search || base.hash) {
    throw new Error('Library API must be an HTTPS URL')
  }
  const endpoint = base.href.replace(/\/$/, '')
  let pending = null
  let stopped = false
  const controller = new AbortController()
  async function get(path) {
    const response = await fetchImpl(`${endpoint}${path}`, {
      redirect: 'error', signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]),
    })
    if (!response.ok) throw new Error(`Library API HTTP ${response.status}`)
    return response.json()
  }
  async function run() {
    if (stopped) return
    const history = await get('/app/history')
    if (!Array.isArray(history.videos)) throw new Error('Invalid library history')
    const videos = history.videos.map(video => {
      if (typeof video.analysis_id !== 'string' || !/^[\w-]{1,100}$/.test(video.analysis_id) ||
          !Number.isFinite(video.uploaded_at) || video.uploaded_at <= 0 ||
          !['done', 'processing', 'failed'].includes(video.status)) throw new Error('Invalid library entry')
      const savedAt = new Date(video.uploaded_at * 1000).toISOString()
      return { ...video, savedAt }
    }).sort((a, b) => b.uploaded_at - a.uploaded_at || b.analysis_id.localeCompare(a.analysis_id))
    const known = new Set(await importedIds())
    let imported = 0
    const failures = []
    // Newest first makes the current report available even during a large backfill.
    for (const video of videos) {
      if (video.status !== 'done' || known.has(`agent-${video.analysis_id}`)) continue
      try {
        const report = await get(`/agent/analysis/${encodeURIComponent(video.analysis_id)}`)
        if (report.analysis_id !== video.analysis_id || report.status !== 'done' ||
            typeof report.message !== 'string' || !report.message.trim() || report.message.length > 60000) {
          throw new Error('Invalid completed library report')
        }
        await saveReport({ analysisId: video.analysis_id,
          fileName: video.filename || `Upload ${video.analysis_id}`, report: report.message,
          uploadedAt: video.savedAt, libraryImported: true })
        known.add(`agent-${video.analysis_id}`)
        imported++
      } catch (error) {
        failures.push({ analysisId: video.analysis_id, error })
      }
    }
    const uploads = videos.map(video => ({ analysisId: video.analysis_id, videoName: video.filename,
      uploadedAt: video.savedAt, status: video.status, reportAvailable: known.has(`agent-${video.analysis_id}`) }))
    await saveManifest(uploads)
    const newestCompleted = videos.find(video => video.status === 'done')
    if (failures.some(failure => failure.analysisId === newestCompleted?.analysis_id)) {
      throw new AggregateError(failures.map(failure => failure.error), 'The latest library report could not be imported')
    }
    return { imported, latestUpload: videos[0] || null, uploads,
      unavailableReports: failures.map(failure => failure.analysisId) }
  }
  return {
    sync() {
      if (!pending) pending = run().finally(() => { pending = null })
      return pending
    },
    async stop() {
      stopped = true
      controller.abort()
      await pending?.catch(() => {})
    },
  }
}
