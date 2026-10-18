const form = document.getElementById('upload-form');
const statusText = document.getElementById('status');
const button = document.getElementById('submit');
const mode = document.getElementById('mode');
let pendingStatusUrl = null;
let completedJobId = null;
let nextFeedbackCursor = null;
let loadingFeedback = false;

async function refreshTextCoach() {
  const status = document.getElementById('text-coach-status');
  const button = document.getElementById('refresh-coach');
  button.disabled = true;
  try {
    const response = await fetch('/api/text-coach');
    if (!response.ok) throw new Error('Text coach is temporarily unavailable.');
    const data = await response.json();
    status.textContent = data.ready ? `Text coaching ready on ${data.number}.` : `Text coaching is not ready: ${data.reason || 'connecting'}.`;
    const link = document.getElementById('text-coach-link');
    link.hidden = !data.ready || !/^\+[1-9]\d{7,14}$/.test(data.number || '');
    if (!link.hidden) link.href = `sms:${data.number}?body=START`;
    document.getElementById('text-coach-goal').textContent = data.goal ? `Your focus: ${data.goal}` : 'No practice goal saved yet. Text GOAL followed by your focus.';
    document.getElementById('text-coach-notifications').textContent = data.paused
      ? 'Texts are paused. Text START to resume.'
      : data.notifications ? 'New-feedback texts are on. Text STOP to pause.' : 'Text START for a message when new feedback is ready. STOP pauses texts.';
    const notes = document.getElementById('text-coach-notes');
    notes.replaceChildren();
    (data.notes || []).slice(-3).forEach(note => {
      const item = document.createElement('li');
      item.textContent = `${note.kind === 'coach' ? 'Human coach note' : note.kind === 'done' ? 'Practice logged' : note.kind === 'checkin' ? 'Check-in' : 'Goal'}: ${note.text}`;
      notes.append(item);
    });
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = false; }
}
document.getElementById('refresh-coach').addEventListener('click', refreshTextCoach);
refreshTextCoach();

function feedbackEntry(entry) {
  const item = document.createElement('li');
  const date = document.createElement('time');
  date.dateTime = entry.savedAt;
  date.textContent = new Date(entry.savedAt).toLocaleString();
  const title = document.createElement('h3');
  title.textContent = entry.videoName;
  const headline = document.createElement('p');
  headline.textContent = entry.feedback.headline || 'Your saved coaching feedback';
  const provenance = document.createElement('p');
  provenance.className = 'provenance';
  provenance.textContent = [entry.feedback.provenance?.generator,
    entry.feedback.provenance?.status === 'partial' ? 'Partial report' : null].filter(Boolean).join(' · ');
  const details = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = 'Read full feedback';
  const report = document.createElement('pre');
  const download = document.createElement('button');
  download.type = 'button';
  download.textContent = 'Download feedback';
  download.hidden = true;
  let loaded = false;
  let fetching = false;
  details.append(summary, report, download);
  details.addEventListener('toggle', async () => {
    if (!details.open || loaded || fetching) return;
    fetching = true;
    report.textContent = 'Loading feedback…';
    try {
      const response = await fetch(`/api/feedback/${entry.id}`);
      if (!response.ok) throw new Error('Could not load feedback. Close and reopen to retry.');
      const data = await response.json();
      report.textContent = data.feedback.report;
      loaded = true;
      download.hidden = false;
    } catch (error) { report.textContent = error.message; }
    finally { fetching = false; }
  });
  download.addEventListener('click', () => {
    const url = URL.createObjectURL(new Blob([report.textContent], {type: 'text/markdown;charset=utf-8'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${entry.videoName}-feedback.md`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  item.append(date, title, headline, provenance, details);
  return item;
}

async function loadFeedbackTimeline(reset = true) {
  if (loadingFeedback) return;
  loadingFeedback = true;
  const status = document.getElementById('history-status');
  const refresh = document.getElementById('refresh-history');
  const more = document.getElementById('more-history');
  refresh.disabled = more.disabled = true;
  status.textContent = 'Loading your feedback…';
  try {
    const query = !reset && nextFeedbackCursor ? `?before=${encodeURIComponent(nextFeedbackCursor)}` : '';
    const response = await fetch(`/api/feedback${query}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load feedback history.');
    const timeline = document.getElementById('feedback-timeline');
    if (reset) timeline.replaceChildren();
    data.items.forEach(entry => timeline.append(feedbackEntry(entry)));
    nextFeedbackCursor = data.nextCursor;
    more.hidden = !nextFeedbackCursor;
    status.textContent = timeline.children.length ? '' : 'No feedback saved yet. Analyze your first clip to start your timeline.';
  } catch (error) { status.textContent = error.message; }
  finally { loadingFeedback = false; refresh.disabled = more.disabled = false; }
}

document.getElementById('refresh-history').addEventListener('click', () => loadFeedbackTimeline());
document.getElementById('more-history').addEventListener('click', () => loadFeedbackTimeline(false));
loadFeedbackTimeline();

function showCoachSync(job) {
  const saved = job.feedback_sync === 'saved';
  document.getElementById('coach-sync').textContent = saved
    ? 'Feedback saved for your text coach. Text your Photon number and ask about this spin.'
    : job.feedback_sync_error || 'Feedback has not reached your text coach yet.';
  document.getElementById('retry-coach').hidden = saved;
  if (saved) { loadFeedbackTimeline(); refreshTextCoach(); }
}

document.getElementById('retry-coach').addEventListener('click', async () => {
  const retry = document.getElementById('retry-coach');
  retry.disabled = true;
  try {
    const response = await fetch(`/api/jobs/${completedJobId}/coach`, {method: 'POST'});
    const data = await response.json();
    if (!response.ok) throw new Error('Could not share this report.');
    showCoachSync({...data, feedback_sync_error: data.error});
  } catch {
    document.getElementById('coach-sync').textContent = 'Could not share feedback. Check that the text coach is running and retry.';
  } finally { retry.disabled = false; }
});

mode.addEventListener('change', () => {
  const local = mode.value === 'local';
  const keyLabel = document.getElementById('key-label');
  if (keyLabel) keyLabel.hidden = local;
  document.getElementById('mode-note').textContent = local
    ? 'Everything runs locally. The report uses rules, with no model-generated timeline captions.'
    : 'Pose processing runs locally. Timestamped video crops and measurements are sent to NVIDIA for coaching.';
});

async function poll(url) {
  try {
    const response = await fetch(url);
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || 'Could not read job status.');
    if (job.status === 'failed') {
      pendingStatusUrl = null;
      throw new Error(job.error);
    }
    if (job.status !== 'completed' || ['pending', 'syncing'].includes(job.feedback_sync)) {
      statusText.textContent = `${job.stage} (${job.elapsed_s}s elapsed)`;
      setTimeout(() => poll(url), 1000);
      return;
    }
    statusText.textContent = `Ready. Processing took ${job.processing_s}s.`;
    const files = job.files;
    const video = document.getElementById('video');
    video.src = files['feedback.mp4'];
    video.load();
    document.getElementById('download-video').href = files['feedback.mp4'] + '?download=1';
    document.getElementById('download-report').href = files['coaching_report.md'] + '?download=1';
    document.getElementById('download-data').href = files['analysis.json'];
    document.getElementById('report').textContent = job.report;
    document.getElementById('provenance').textContent = `Generated by: ${job.generator}${job.model ? ' (' + job.model + ')' : ''}.`;
    document.getElementById('warning').textContent = job.warning || '';
    document.getElementById('results').hidden = false;
    completedJobId = job.id;
    showCoachSync(job);
    pendingStatusUrl = null;
    button.disabled = false;
    button.textContent = 'Upload and analyze';
  } catch (error) {
    statusText.textContent = error.message;
    button.disabled = false;
    button.textContent = pendingStatusUrl ? 'Retry status check' : 'Upload and analyze';
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
  statusText.textContent = 'Uploading...';
  try {
    const body = new FormData(form);
    if (mode.value === 'local') body.delete('api_key');
    const response = await fetch('/api/jobs', {method: 'POST', body});
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || 'Upload failed.');
    const keyInput = document.getElementById('api-key');
    if (keyInput) keyInput.value = '';
    pendingStatusUrl = job.status_url;
    history.replaceState(null, '', `?job=${encodeURIComponent(job.id)}`);
    await poll(pendingStatusUrl);
  } catch (error) {
    statusText.textContent = error.message;
    button.disabled = false;
  }
});

// Keep a completed test run inspectable after refresh, while the server runs.
const restoredJob = new URLSearchParams(location.search).get('job');
if (restoredJob && /^[a-f0-9]{32}$/.test(restoredJob)) {
  pendingStatusUrl = `/api/jobs/${restoredJob}`;
  button.disabled = true;
  poll(pendingStatusUrl);
}
