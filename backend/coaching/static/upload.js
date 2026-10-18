const form = document.getElementById('upload-form');
const statusText = document.getElementById('status');
const button = document.getElementById('submit');
const mode = document.getElementById('mode');
let pendingStatusUrl = null;
let confirmingJob = null;
const confirmation = document.getElementById('confirmation');
const confirmedElement = document.getElementById('confirmed-element');
const confirmButton = document.getElementById('confirm-button');
const retryButton = document.getElementById('retry-report');
let retryJobId = null;

function markerFields() {
  const family = confirmedElement.selectedOptions[0].dataset.family;
  document.getElementById('phase-markers').hidden = family === 'unknown';
  document.getElementById('first-marker-label').textContent = family === 'jump' ? 'Takeoff time (seconds, optional)' : 'Hold starts (seconds, optional)';
  document.getElementById('second-marker-label').textContent = family === 'jump' ? 'Landing time (seconds, optional)' : 'Hold ends (seconds, optional)';
  document.getElementById('phase-help').textContent = family === 'jump'
    ? 'Use the preview to mark takeoff and landing. Without markers, jump phase boundaries remain uncertain.'
    : family === 'spin' ? 'Optionally mark the intended hold. A sit-spin lower-position candidate may be suggested automatically.'
    : 'The report will describe general movement without assuming a spin or jump.';
}
confirmedElement.addEventListener('change', () => {
  document.getElementById('first-marker').value = '';
  document.getElementById('second-marker').value = '';
  markerFields();
});

async function fetchLocal(url, options) {
  try {
    return await fetch(url, options);
  } catch {
    throw new Error('The local analysis server is offline. Start it with .video-venv/bin/python webapp.py --ask-key --detach, then refresh this page.');
  }
}

mode.addEventListener('change', () => {
  const local = mode.value === 'local';
  const keyLabel = document.getElementById('key-label');
  if (keyLabel) keyLabel.hidden = local;
  document.getElementById('perceptron-track').disabled=local;
  const personKeyLabel=document.getElementById('perceptron-key-label');
  if (personKeyLabel) personKeyLabel.hidden=local;
  document.getElementById('tracking-note').hidden=local;
  document.getElementById('mode-note').textContent = local
    ? 'Everything runs locally. The report uses rules, with no model-generated timeline captions.'
    : `Pose processing runs locally. A compact video and timestamped body crops are sent to ${document.getElementById('mode-note').dataset.gemini==='true' ? 'Gemini first, with NVIDIA as fallback' : 'NVIDIA'} to identify the move before confirmation, then with measurements for coaching.`;
});
mode.dispatchEvent(new Event('change'));

async function poll(url) {
  try {
    const response = await fetchLocal(url);
    const job = await response.json();
    if (response.status === 404) {
      pendingStatusUrl = null;
      history.replaceState(null, '', location.pathname);
      throw new Error('This test job expired after the server restarted. Choose a video and click Upload and analyze again.');
    }
    if (!response.ok) throw new Error(job.error || 'Could not read job status.');
    if (job.status === 'failed') {
      pendingStatusUrl = null;
      retryJobId = job.can_retry ? job.id : null;
      retryButton.hidden = !retryJobId;
      retryButton.disabled = false;
      throw new Error(job.error);
    }
    if (job.status === 'needs_confirmation') {
      confirmingJob = job.id;
      confirmedElement.value = job.selected_element;
      const suggestion = job.suggestion;
      const source = suggestion.provider && suggestion.provider !== 'Local'
        ? `${suggestion.provider} (${suggestion.model}); ${suggestion.confidence} model confidence (self-reported)`
        : 'Local pose heuristic';
      const evidence = (suggestion.evidence || []).map(item => `${item.time_s.toFixed(1)}s: ${item.observation}`).join(' ');
      const fallback = (suggestion.fallback_reasons || []).map(item => item.reason).join(' ');
      document.getElementById('suggestion').textContent = `Suggestion: ${suggestion.label}. ${suggestion.reason} Source: ${source}. ${suggestion.input_mode || ''}. ${evidence} ${fallback} Please confirm or correct it.`;
      const preview = document.getElementById('preview');
      preview.src = job.preview_url;
      preview.load();
      for (const id of ['first-marker','second-marker']) {
        document.getElementById(id).max = job.duration_s;
        document.getElementById(id).value = '';
      }
      markerFields();
      confirmation.hidden = false;
      confirmButton.disabled = false;
      statusText.textContent = 'Tracking and move identification complete. Confirm the element below.';
      button.disabled = false;
      button.textContent = 'Inspect another video';
      pendingStatusUrl = null;
      return;
    }
    if (job.status !== 'completed') {
      statusText.textContent = `${job.stage} (${job.elapsed_s}s elapsed)`;
      setTimeout(() => poll(url), 1000);
      return;
    }
    statusText.textContent = `Ready. Processing took ${job.processing_s}s.`;
    retryButton.hidden = true;
    const files = job.files;
    const video = document.getElementById('video');
    video.src = files['feedback.mp4'];
    video.load();
    document.getElementById('download-video').href = files['feedback.mp4'] + '?download=1';
    document.getElementById('download-report').href = files['coaching_report.md'] + '?download=1';
    document.getElementById('download-data').href = files['analysis.json'];
    const tracking=job.person_tracking;
    document.getElementById('tracking-result').textContent=tracking
      ? tracking.status==='completed'
        ? `Person box: Perceptron (${tracking.model_anchor_count} observations, ${tracking.elapsed_s}s). Cyan boxes use nearby anchors and matched body points to include hands and skates. Gray boxes use MediaPipe alone. Green points show the body joints.`
        : tracking.warning || 'Person box and body points: local MediaPipe.'
      : '';
    const trackingLink=document.getElementById('download-tracking');
    trackingLink.hidden=!files['person_tracking.json'];
    if (files['person_tracking.json']) trackingLink.href=files['person_tracking.json']+'?download=1';
    const reportResponse = await fetchLocal(files['coaching_report.md']);
    if (!reportResponse.ok) throw new Error('Could not load the coaching report.');
    document.getElementById('report').textContent = await reportResponse.text();
    document.getElementById('report').closest('details').querySelector('summary').textContent='Coaching report and score';
    const visual = Boolean(job.element_analysis?.visual_model);
    document.getElementById('provenance').textContent = visual
      ? `Video coaching by ${job.model}. Summary, detailed feedback and captions use the same assessment. ISU-based coaching opinion; no official score.`
      : `Summary: measured-evidence checks. Detailed coaching: ${job.generator}${job.model ? ' (' + job.model + ')' : ''}.`;
    document.getElementById('warning').textContent = job.warning || '';
    document.getElementById('quick-feedback').textContent = job.summary?.line || 'No confident overall assessment is available.';
    const identification = job.suggestion || job.element_analysis?.suggestion;
    const identifiedBy = identification?.model
      ? ` Suggested by ${identification.provider} (${identification.model}).`
      : identification?.fallback_used ? ' Automatic recognition unavailable; local suggestion used.' : '';
    document.getElementById('confirmed-label').textContent = job.element_analysis ? `Element: ${job.element_analysis.label}.${identifiedBy}` : '';
    const isu = job.element_analysis?.isu_assessment;
    document.getElementById('isu-section').hidden = !isu;
    const ruleList = document.getElementById('isu-checks');
    ruleList.replaceChildren();
    if (isu) {
      document.getElementById('isu-policy').textContent = visual
        ? 'Visible strengths and improvement priorities, linked to ISU criteria. These are model coaching opinions, not official technical calls.'
        : isu.policy;
      const checks = visual ? isu.checks.filter(check => check.visual_opinions?.length) : isu.checks;
      for (const check of checks) {
        const row = document.createElement('li');
        const link = document.createElement('a');
        link.href = check.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = `${check.title} — ${check.status_label || check.status.replaceAll('_', ' ')} (p. ${check.page})`;
        row.append(link, document.createTextNode(`: ${check.criterion} ${check.explanation}`));
        ruleList.append(row);
      }
      if (!checks.length) {
        const row = document.createElement('li');
        row.textContent = visual ? 'See the phase feedback for visible coaching observations.' : 'Choose a supported spin or jump to select relevant criteria.';
        ruleList.append(row);
      }
    }
    confirmation.hidden = true;
    document.getElementById('results').hidden = false;
    pendingStatusUrl = null;
    button.disabled = false;
    button.textContent = 'Upload and inspect';
  } catch (error) {
    statusText.textContent = error.message;
    button.disabled = false;
    button.textContent = pendingStatusUrl ? 'Retry status check' : 'Upload and inspect';
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  if (pendingStatusUrl) {
    await poll(pendingStatusUrl);
    return;
  }
  document.getElementById('results').hidden = true;
  retryButton.hidden = true;
  retryJobId = null;
  document.getElementById('preview').pause();
  confirmation.hidden = true;
  statusText.textContent = 'Uploading...';
  try {
    const body = new FormData(form);
    if (mode.value === 'local') {
      body.delete('api_key');
      body.delete('perceptron_key');
      body.delete('perceptron_track');
    }
    const response = await fetchLocal('/api/jobs', {method: 'POST', body});
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || 'Upload failed.');
    const keyInput = document.getElementById('api-key');
    if (keyInput) keyInput.value = '';
    const personKeyInput=document.getElementById('perceptron-key');
    if (personKeyInput) personKeyInput.value='';
    pendingStatusUrl = job.status_url;
    history.replaceState(null, '', `?job=${encodeURIComponent(job.id)}`);
    await poll(pendingStatusUrl);
  } catch (error) {
    statusText.textContent = error.message;
    button.disabled = false;
  }
});

retryButton.addEventListener('click', async () => {
  if (!retryJobId) return;
  retryButton.disabled = true;
  try {
    const response = await fetchLocal(`/api/jobs/${retryJobId}/retry`, {method:'POST'});
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || 'Could not retry the report.');
    retryButton.hidden = true;
    pendingStatusUrl = job.status_url;
    button.disabled = true;
    await poll(pendingStatusUrl);
  } catch (error) {
    statusText.textContent = error.message;
    retryButton.disabled = false;
  }
});

document.getElementById('confirm-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!confirmingJob) return;
  confirmButton.disabled = true;
  try {
    const family = confirmedElement.selectedOptions[0].dataset.family;
    const first = document.getElementById('first-marker').value;
    const second = document.getElementById('second-marker').value;
    const markers = {};
    if (family !== 'unknown' && (first !== '' || second !== '')) {
      if (first === '' || second === '') throw new Error('Enter both phase times, or leave both blank.');
      const names = family === 'jump' ? ['takeoff_s','landing_s'] : ['hold_start_s','hold_end_s'];
      markers[names[0]] = Number(first);
      markers[names[1]] = Number(second);
    }
    const response = await fetchLocal(`/api/jobs/${confirmingJob}/confirm`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({element:confirmedElement.value, markers})
    });
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || 'Could not confirm the element.');
    pendingStatusUrl = job.status_url;
    confirmingJob = null;
    document.getElementById('preview').pause();
    confirmation.hidden = true;
    button.disabled = true;
    statusText.textContent = 'Generating confirmed-element feedback...';
    await poll(pendingStatusUrl);
  } catch (error) {
    statusText.textContent = error.message;
    confirmButton.disabled = false;
  }
});

// Keep a completed test run inspectable after refresh, while the server runs.
const restoredJob = new URLSearchParams(location.search).get('job');
if (restoredJob && /^[a-f0-9]{32}$/.test(restoredJob)) {
  pendingStatusUrl = `/api/jobs/${restoredJob}`;
  button.disabled = true;
  poll(pendingStatusUrl);
}
