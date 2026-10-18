const form = document.getElementById('upload-form');
const statusText = document.getElementById('status');
const button = document.getElementById('submit');
const mode = document.getElementById('mode');
const fileInput = document.getElementById('file');
const stage = document.getElementById('video');
const pick = document.getElementById('pick');
const report = document.getElementById('report');
const reportToggle = document.getElementById('toggle-report');
const playButton = document.getElementById('play');
const scrub = document.getElementById('scrub');
const clock = document.getElementById('clock');
const cue = document.getElementById('cue');
const cueTime = document.getElementById('cue-time');
const reading = document.getElementById('reading');
const notes = document.getElementById('notes');
const measure = document.getElementById('measure');
const measureBody = document.getElementById('measure-body');
const frames = document.getElementById('frames');
const analysisFrames = document.getElementById('analysis-frames');
const sessionTitle = document.getElementById('session-title');
const homeLine = document.getElementById('home-line');
const thread = document.getElementById('thread');
const planList = document.getElementById('plan-list');
const planEmpty = document.getElementById('plan-empty');
const theme = document.querySelector('meta[name="theme-color"]');

let pendingStatusUrl = null;
let previewUrl = null;
let colorSamples = [];
let lastColorAt = -1;
let scrubbing = false;
let coaching = {cues: [], paragraphs: []};
let analysisTab = 'overview';
let frameToken = 0;
let frameMarks = [];
let clipWhen = null;
let planItems = [];
let planTab = 'plan';
let homeTab = 'foryou';
let playbackRate = 1;

document.body.dataset.screen = 'home';
document.body.dataset.tab = 'overview';

mode.addEventListener('change', () => {
  const local = mode.value === 'local';
  const keyLabel = document.getElementById('key-label');
  if (keyLabel) keyLabel.hidden = local;
  document.getElementById('mode-note').textContent = local
    ? 'Everything runs locally. The report uses rules, with no model-generated timeline captions.'
    : 'Pose processing runs locally. Timestamped video crops and measurements are sent to NVIDIA for coaching.';
});

function showScreen(name) {
  document.querySelectorAll('.screen').forEach((screen) => {
    screen.classList.toggle('is-on', screen.dataset.screen === name);
  });
  document.querySelectorAll('nav [data-go]').forEach((control) => {
    if (control.dataset.go === name) control.setAttribute('aria-current', 'page');
    else control.removeAttribute('aria-current');
  });
  document.body.dataset.screen = name;
  const heading = document.getElementById('screen-heading');
  heading.textContent = name === 'plan' ? 'Training Plan' : name === 'coach' ? 'Coach' : name === 'analysis' ? 'Analysis' : '';
  const menu = document.getElementById('more-panel');
  if (menu) {
    menu.hidden = true;
    document.getElementById('more').setAttribute('aria-expanded', 'false');
  }
  if (name === 'home') setHomeTab('foryou');
}

function setHomeTab(name) {
  homeTab = name;
  document.querySelectorAll('[data-home-tab]').forEach((tab) => {
    tab.setAttribute('aria-selected', tab.dataset.homeTab === name ? 'true' : 'false');
  });
  applyPanes();
}

function applyPanes() {
  const clip = document.body.classList.contains('has-clip');
  document.querySelectorAll('#home [data-pane]').forEach((pane) => {
    const names = pane.dataset.pane.split(/\s+/);
    const onTab = names.includes(homeTab);
    if (pane.id === 'recent') pane.hidden = !(onTab && clip);
    else if (pane.id === 'library-empty') pane.hidden = !(homeTab === 'library' && !clip);
    else pane.hidden = !onTab;
  });
}

document.querySelectorAll('[data-home-tab]').forEach((tab) => {
  tab.addEventListener('click', () => {
    setHomeTab(tab.dataset.homeTab);
    if (tab.dataset.homeTab === 'chat') document.getElementById('home-chat-input').focus();
  });
});

document.querySelectorAll('[data-go]').forEach((control) => {
  control.addEventListener('click', () => showScreen(control.dataset.go));
});

function fmt(seconds) {
  if (!Number.isFinite(seconds)) return '0:00';
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

function plain(text) {
  return text
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[*_`]/g, '')
    .replace(/^#+\s*/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function field(body, name) {
  const match = body.match(new RegExp('^' + name + ':\\s*([\\s\\S]*?)(?=\\n\\s*(?:Observation|Advice|Cue|Caption|Measured evidence)\\s*:|$)', 'im'));
  return match ? plain(match[1]) : '';
}

function firstSentence(text) {
  const clean = plain(text).replace(/\s+/g, ' ');
  const match = clean.match(/^.{12,}?[.!?]/);
  return match ? match[0] : clean;
}

function parseReport(text) {
  const clean = text.replace(/\r/g, '');
  const sectionRe = /^###\s+(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*seconds?\s*$/gim;
  const marks = [...clean.matchAll(sectionRe)];
  const cues = marks.map((mark, index) => {
    const from = mark.index + mark[0].length;
    const to = index + 1 < marks.length ? marks[index + 1].index : clean.length;
    const body = clean.slice(from, to);
    return {
      start: Number(mark[1]),
      end: Number(mark[2]),
      observation: field(body, 'Observation'),
      advice: field(body, 'Advice'),
      cue: field(body, 'Cue')
    };
  });
  const paragraphs = clean.split(/\n\s*\n/).map(plain).filter((part) => {
    if (!part || part.length < 40) return false;
    if (/^(measured evidence|generated by|model:|hackathon|model-generated|the model received|no model|inputs also|inputs include|still frames|---)/i.test(part)) return false;
    if (/^###/.test(part)) return false;
    return true;
  });
  if (!cues.length) {
    paragraphs.forEach((part) => {
      const range = part.match(/(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*seconds/i);
      const around = part.match(/around\s+(\d+(?:\.\d+)?)\s*seconds/i);
      if (range) cues.push({start: Number(range[1]), end: Number(range[2]), observation: part, advice: '', cue: ''});
      else if (around) cues.push({start: Math.max(0, Number(around[1]) - 0.5), end: Number(around[1]) + 0.5, observation: part, advice: '', cue: ''});
    });
  }
  return {cues, paragraphs};
}

function applyAtmosphere(video) {
  const canvas = document.createElement('canvas');
  const size = 28;
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext('2d', {willReadFrequently: true});
  try {
    context.drawImage(video, 0, 0, size, size);
  } catch (error) {
    return;
  }
  const pixels = context.getImageData(0, 0, size, size).data;
  let red = 0;
  let green = 0;
  let blue = 0;
  let count = 0;
  for (let index = 0; index < pixels.length; index += 16) {
    red += pixels[index];
    green += pixels[index + 1];
    blue += pixels[index + 2];
    count += 1;
  }
  red /= count;
  green /= count;
  blue /= count;
  const luma = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255;
  if (luma < 0.08) return;
  colorSamples.push({red, green, blue});
  if (colorSamples.length > 10) colorSamples.shift();
  red = colorSamples.reduce((sum, sample) => sum + sample.red, 0) / colorSamples.length;
  green = colorSamples.reduce((sum, sample) => sum + sample.green, 0) / colorSamples.length;
  blue = colorSamples.reduce((sum, sample) => sum + sample.blue, 0) / colorSamples.length;
  const gray = (red + green + blue) / 3;
  const keep = 0.7;
  red = gray + (red - gray) * keep;
  green = gray + (green - gray) * keep;
  blue = gray + (blue - gray) * keep;
  const tone = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255;
  const mix = (channel, target, amount) => Math.round(channel + (target - channel) * amount);
  const light = tone > 0.46;
  const base = light
    ? [mix(red, 246, 0.62), mix(green, 246, 0.62), mix(blue, 246, 0.62)]
    : [mix(red, 18, 0.38), mix(green, 20, 0.38), mix(blue, 22, 0.38)];
  const ink = light ? '#1b1d20' : '#f3f4f2';
  const muted = light ? 'rgba(27, 29, 32, 0.64)' : 'rgba(243, 244, 242, 0.72)';
  const hair = light ? 'rgba(27, 29, 32, 0.18)' : 'rgba(243, 244, 242, 0.24)';
  const frostAlpha = light ? 0.5 : 0.46;
  const strongAlpha = light ? 0.9 : 0.86;
  const washAlpha = light ? 0.58 : 0.55;
  const topAlpha = light ? 0.22 : 0.28;
  const navAlpha = light ? 0.7 : 0.58;
  const set = (name, value) => document.body.style.setProperty(name, value);
  set('--ink', ink);
  set('--muted', muted);
  set('--hair', hair);
  set('--frost', `rgba(${base[0]}, ${base[1]}, ${base[2]}, ${frostAlpha})`);
  set('--frost-strong', `rgba(${base[0]}, ${base[1]}, ${base[2]}, ${strongAlpha})`);
  set('--wash', `rgba(${base[0]}, ${base[1]}, ${base[2]}, ${washAlpha})`);
  set('--wash-top', `rgba(${base[0]}, ${base[1]}, ${base[2]}, ${topAlpha})`);
  set('--nav', `rgba(${base[0]}, ${base[1]}, ${base[2]}, ${navAlpha})`);
  set('--field', `rgb(${base[0]}, ${base[1]}, ${base[2]})`);
  document.documentElement.style.colorScheme = light ? 'light' : 'dark';
  if (theme) theme.setAttribute('content', `rgb(${base[0]}, ${base[1]}, ${base[2]})`);
}

function showUploadedVideo(file) {
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(file);
  colorSamples = [];
  lastColorAt = -1;
  stage.src = previewUrl;
  stage.muted = true;
  stage.loop = true;
  stage.load();
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!motion) stage.play().catch(() => {});
  const clipName = file.name.replace(/\.[^.]+$/, '');
  document.getElementById('clip-name').textContent = clipName;
  sessionTitle.textContent = clipName;
  clipWhen = file.lastModified ? new Date(file.lastModified) : new Date();
  document.body.classList.add('has-clip');
  document.body.classList.remove('done');
  playbackRate = 1;
  stage.playbackRate = 1;
  const speed = document.getElementById('tool-speed');
  if (speed) speed.textContent = '1×';
  applyHome();
  homeLine.textContent = 'for coaches and skaters.';
  homeLine.classList.remove('is-note');
  document.getElementById('results').hidden = true;
  report.hidden = true;
  coaching = {cues: [], paragraphs: []};
  resetConversation('The clip is in. Read it, and I will stay with what it shows.');
  fillPlan([]);
  renderAi();
  setTab('overview');
  showScreen('playback');
}

fileInput.addEventListener('change', () => {
  const file = fileInput.files && fileInput.files[0];
  if (file) showUploadedVideo(file);
});

['dragenter', 'dragover'].forEach((name) => {
  document.body.addEventListener(name, (event) => {
    event.preventDefault();
    document.body.classList.add('is-dragging');
  });
});

['dragleave', 'drop'].forEach((name) => {
  document.body.addEventListener(name, (event) => {
    event.preventDefault();
    if (name === 'dragleave' && event.target !== document.body) return;
    document.body.classList.remove('is-dragging');
  });
});

document.body.addEventListener('drop', (event) => {
  const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  showUploadedVideo(file);
});

document.getElementById('session').addEventListener('click', () => {
  const settings = document.getElementById('settings');
  settings.hidden = !settings.hidden;
  if (!settings.hidden) showScreen('home');
});

document.getElementById('upload-form').addEventListener('click', (event) => {
  if (event.target.closest('#settings, #session, button, a, input, select, label')) return;
  fileInput.click();
});

function togglePlay() {
  if (!stage.src) {
    showScreen('home');
    return;
  }
  if (stage.paused) {
    stage.muted = false;
    stage.play().catch(() => {
      stage.muted = true;
      stage.play().catch(() => {});
    });
  } else {
    stage.pause();
  }
}

playButton.addEventListener('click', togglePlay);
document.getElementById('stage-hit').addEventListener('click', togglePlay);

function paintTime() {
  clock.textContent = fmt(stage.currentTime);
  const duration = document.getElementById('duration');
  if (duration) duration.textContent = Number.isFinite(stage.duration) ? fmt(stage.duration) : '0:00';
}

stage.addEventListener('play', () => {
  playButton.setAttribute('aria-pressed', 'true');
  playButton.setAttribute('aria-label', 'Pause');
});

stage.addEventListener('pause', () => {
  playButton.setAttribute('aria-pressed', 'false');
  playButton.setAttribute('aria-label', 'Play');
});

stage.addEventListener('loadedmetadata', () => {
  scrub.disabled = !Number.isFinite(stage.duration);
  paintTime();
  renderRecent();
});

stage.addEventListener('loadeddata', () => {
  applyAtmosphere(stage);
  buildFrames();
});

function stepFrame(direction) {
  if (!Number.isFinite(stage.duration)) return;
  stage.pause();
  const next = stage.currentTime + direction / 30;
  stage.currentTime = Math.min(stage.duration, Math.max(0, next));
}

document.getElementById('step-back').addEventListener('click', () => stepFrame(-1));
document.getElementById('step-forward').addEventListener('click', () => stepFrame(1));

document.getElementById('tool-analysis').addEventListener('click', () => showScreen('analysis'));

document.getElementById('tool-next').addEventListener('click', () => {
  if (!frameMarks.length || !Number.isFinite(stage.duration)) return;
  stage.pause();
  const time = stage.currentTime || 0;
  const next = frameMarks.find((mark) => mark > time + 0.08);
  stage.currentTime = next == null ? frameMarks[0] : next;
});

document.getElementById('tool-speed').addEventListener('click', () => {
  const rates = [1, 0.5, 0.25];
  const index = rates.findIndex((rate) => Math.abs(rate - playbackRate) < 0.01);
  playbackRate = rates[(index + 1) % rates.length];
  stage.playbackRate = playbackRate;
  document.getElementById('tool-speed').textContent = playbackRate === 1 ? '1×' : `${playbackRate}×`;
});

stage.addEventListener('timeupdate', () => {
  if (colorSamples.length < 10 && stage.readyState >= 2 && stage.currentTime > 0.15 && stage.currentTime - lastColorAt > 0.2) {
    lastColorAt = stage.currentTime;
    applyAtmosphere(stage);
  }
  if (!scrubbing && Number.isFinite(stage.duration) && stage.duration > 0) {
    scrub.value = String(Math.round((stage.currentTime / stage.duration) * 1000));
  }
  paintTime();
  markActiveFrame();
  if (analysisTab === 'technique') renderTechnique();
});

scrub.addEventListener('input', () => {
  if (!Number.isFinite(stage.duration) || stage.duration <= 0) return;
  scrubbing = true;
  stage.currentTime = (Number(scrub.value) / 1000) * stage.duration;
  paintTime();
  markActiveFrame();
  if (analysisTab === 'technique') renderTechnique();
});

scrub.addEventListener('change', () => {
  scrubbing = false;
});

function cueAt(time) {
  return coaching.cues.find((item) => time >= item.start && time < item.end) || null;
}

function readingWord() {
  const text = `${coaching.paragraphs[0] || ''} ${coaching.cues[0]?.observation || ''}`.toLowerCase();
  if (!coaching.paragraphs.length && !coaching.cues.length) return 'Unread';
  if (/promising/.test(text)) return 'Promising';
  if (/priority|clearer|review/.test(text)) return 'Review';
  return 'Noted';
}

function uniqueLines(lines) {
  const seen = new Set();
  return lines.filter((line) => {
    const clean = firstSentence(line || '');
    if (!clean || seen.has(clean)) return false;
    seen.add(clean);
    return true;
  }).map((line) => firstSentence(line));
}

function addNote(text) {
  if (!text) return;
  const item = document.createElement('li');
  item.textContent = text;
  notes.append(item);
}

let techniqueKey = '';

function renderTechnique() {
  const current = cueAt(stage.currentTime || 0) || coaching.cues[0];
  const key = current ? String(current.start) : 'none';
  if (key === techniqueKey) return;
  techniqueKey = key;
  renderFeedback();
}

function titleCase(text) {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (!clean) return '';
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

function rowsFromText(text) {
  const rows = [];
  const seen = new Set();
  const add = (name, value, note) => {
    const label = titleCase(name).replace(/:$/, '').replace(/\s+/g, ' ').trim();
    const key = `${label}|${value}`;
    if (!label || !/[A-Za-z]{3,}/.test(label) || seen.has(key)) return;
    seen.add(key);
    rows.push({name: label, value, note: (note || '').replace(/\s+/g, ' ').trim()});
  };
  const source = text || '';
  const median = /([A-Za-z][A-Za-z ]{1,42}?)\s+median\s+(\d+(?:\.\d+)?)\s*(?:deg(?:rees)?|°)\s*(?:;\s*([^;\n]+))?/gi;
  let match;
  while ((match = median.exec(source))) add(match[1], `${match[2]}°`, match[3] || '');
  const named = /([A-Za-z][A-Za-z ]{1,42}?):\s*(\d+(?:\.\d+)?)\s*(?:deg(?:rees)?|°)(?:\s*\(([^)]+)\))?/gi;
  while ((match = named.exec(source))) add(match[1], `${match[2]}°`, match[3] || '');
  if (!rows.length) {
    const interval = /(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)\s*(?:seconds|secs|s)\b/gi;
    while ((match = interval.exec(source))) {
      const around = source.slice(Math.max(0, match.index - 60), match.index).split(/[.\n]/).pop() || '';
      add(/[A-Za-z]{4,}/.test(around) ? around : 'Interval', `${match[1]}–${match[2]} s`, '');
    }
  }
  return rows;
}

function reportBlob() {
  return [
    report.textContent || '',
    ...coaching.paragraphs,
    ...coaching.cues.map((item) => [item.observation, item.advice, item.cue].filter(Boolean).join('\n'))
  ].join('\n');
}

function renderMeasures() {
  if (analysisTab !== 'technique') {
    measure.hidden = true;
    return;
  }
  const current = cueAt(stage.currentTime || 0) || coaching.cues[0];
  const local = current ? [current.observation, current.advice, current.cue].filter(Boolean).join('\n') : '';
  const seen = new Set();
  const rows = [];
  rowsFromText(local).concat(rowsFromText(reportBlob())).forEach((row) => {
    const key = `${row.name}|${row.value}`;
    if (seen.has(key)) return;
    seen.add(key);
    rows.push(row);
  });
  measureBody.replaceChildren();
  if (!rows.length) {
    const row = document.createElement('div');
    row.className = 'm-row';
    const name = document.createElement('p');
    name.className = 'm-name';
    name.textContent = document.body.classList.contains('done') ? 'No measurement in this note.' : 'Read the clip for measurements.';
    row.append(name);
    measureBody.append(row);
  } else {
    rows.slice(0, 4).forEach((item) => {
      const row = document.createElement('div');
      row.className = 'm-row';
      const top = document.createElement('div');
      top.className = 'm-top';
      const name = document.createElement('p');
      name.className = 'm-name';
      name.textContent = item.name;
      const value = document.createElement('p');
      value.className = 'm-value';
      value.textContent = item.value;
      top.append(name, value);
      row.append(top);
      if (item.note) {
        const note = document.createElement('p');
        note.className = 'm-note';
        note.textContent = item.note;
        row.append(note);
      }
      measureBody.append(row);
    });
  }
  measure.hidden = false;
}

function renderFeedback() {
  notes.replaceChildren();
  reading.textContent = coaching.paragraphs.length || coaching.cues.length ? 'From the clip' : 'Unread';
  const waiting = document.body.classList.contains('has-clip')
    ? 'The clip is here. Read it when you are ready.'
    : 'Footage will fill this screen.';
  if (analysisTab === 'technique') {
    const current = cueAt(stage.currentTime || 0) || coaching.cues[0];
    cueTime.textContent = current ? `${fmt(current.start)} – ${fmt(current.end)}` : 'Technique';
    cue.textContent = waiting;
    renderMeasures();
    return;
  }
  if (analysisTab === 'comparison') {
    cueTime.textContent = 'Comparison';
    const first = coaching.cues[0];
    const last = coaching.cues.length > 1 ? coaching.cues[coaching.cues.length - 1] : null;
    cue.textContent = first && last
      ? 'Two positions from this clip.'
      : 'A comparison appears once two positions in this clip have been read.';
    if (first) addNote(firstSentence(first.observation || first.cue || first.advice || ''));
    if (last) addNote(firstSentence(last.observation || last.cue || last.advice || ''));
    renderMeasures();
    return;
  }
  cueTime.textContent = 'Overview';
  const lines = uniqueLines([
    ...coaching.cues.map((item) => item.observation || item.cue || item.advice),
    ...coaching.paragraphs
  ]);
  cue.textContent = lines[0] || waiting;
  lines.slice(1, 4).forEach(addNote);
  const current = cueAt(stage.currentTime || 0) || coaching.cues[0];
  techniqueKey = analysisTab === 'technique' && current ? String(current.start) : '';
  renderMeasures();
}

function setTab(name) {
  analysisTab = name;
  document.body.dataset.tab = name;
  techniqueKey = '';
  document.querySelectorAll('.tabs button').forEach((tab) => {
    tab.setAttribute('aria-selected', tab.dataset.tab === name ? 'true' : 'false');
  });
  renderFeedback();
}

document.querySelectorAll('.tabs button').forEach((tab) => {
  tab.addEventListener('click', () => setTab(tab.dataset.tab));
});

function phaseNames() {
  const hay = (report.textContent || '').toLowerCase();
  if (/\btake[\s-]?off\b/.test(hay) && /\blanding\b/.test(hay)) {
    return ['Approach', 'Takeoff', 'Air', 'Landing', 'Exit'];
  }
  return ['Entry', 'Hold', 'Rise', 'Exit'];
}

function framePhases() {
  const duration = Number.isFinite(stage.duration) ? stage.duration : 0;
  if (duration <= 0) return [];
  const names = phaseNames();
  return names.map((label, index) => {
    const mark = (index + 0.5) / names.length;
    const time = Math.max(0.05, Math.min(duration - 0.05, duration * mark));
    return {time, label};
  });
}

function markActiveFrame() {
  if (!frameMarks.length) return;
  const time = stage.currentTime || 0;
  let nearest = 0;
  frameMarks.forEach((mark, index) => {
    if (Math.abs(mark - time) < Math.abs(frameMarks[nearest] - time)) nearest = index;
  });
  [frames, analysisFrames].forEach((box) => {
    [...box.children].forEach((button, index) => {
      if (index === nearest) button.setAttribute('aria-current', 'true');
      else button.removeAttribute('aria-current');
    });
  });
}

function frameButton(phase, src, openAnalysis) {
  const button = document.createElement('button');
  button.type = 'button';
  const image = document.createElement('img');
  image.alt = '';
  image.src = src;
  const label = document.createElement('span');
  label.className = 'label';
  label.textContent = phase.label;
  button.append(image, label);
  button.addEventListener('click', () => {
    stage.pause();
    stage.currentTime = phase.time;
    setTab('technique');
    if (openAnalysis) showScreen('analysis');
  });
  return button;
}

async function buildFrames() {
  const phases = framePhases();
  const token = ++frameToken;
  if (!phases.length) {
    frames.replaceChildren();
    analysisFrames.replaceChildren();
    frameMarks = [];
    return;
  }
  if (stage.readyState < 2) return;
  const wasPaused = stage.paused;
  const restore = stage.currentTime;
  stage.pause();
  const canvas = document.createElement('canvas');
  canvas.width = 152;
  canvas.height = 96;
  const context = canvas.getContext('2d');
  const shots = [];
  for (const phase of phases) {
    if (token !== frameToken) return;
    await new Promise((resolve) => {
      const paint = () => {
        try { context.drawImage(stage, 0, 0, canvas.width, canvas.height); } catch (error) { /* keep the empty frame */ }
        resolve();
      };
      if (Math.abs((stage.currentTime || 0) - phase.time) < 0.04) {
        paint();
        return;
      }
      stage.addEventListener('seeked', function onSeek() {
        stage.removeEventListener('seeked', onSeek);
        paint();
      });
      stage.currentTime = phase.time;
    });
    let src = '';
    try { src = canvas.toDataURL('image/jpeg', 0.72); } catch (error) { src = ''; }
    shots.push(src);
  }
  if (token !== frameToken) return;
  frames.replaceChildren(...phases.map((phase, index) => frameButton(phase, shots[index], true)));
  analysisFrames.replaceChildren(...phases.map((phase, index) => frameButton(phase, shots[index], false)));
  const still = document.getElementById('recent-still');
  if (shots[0]) {
    still.src = shots[0];
    still.hidden = false;
  }
  frameMarks = phases.map((phase) => phase.time);
  stage.currentTime = restore;
  if (!wasPaused) stage.play().catch(() => {});
  markActiveFrame();
  renderRecent();
}

document.getElementById('more').addEventListener('click', () => {
  const menu = document.getElementById('more-panel');
  menu.hidden = !menu.hidden;
  document.getElementById('more').setAttribute('aria-expanded', String(!menu.hidden));
});

document.getElementById('more-setup').addEventListener('click', () => {
  document.getElementById('settings').hidden = false;
  document.getElementById('more-panel').hidden = true;
  showScreen('home');
});

function pushMessage(role, text) {
  const item = document.createElement('div');
  item.className = `msg ${role}`;
  const who = document.createElement('div');
  who.className = 'who';
  who.textContent = role === 'coach' ? 'Coach' : 'You';
  const body = document.createElement('p');
  body.textContent = text;
  item.append(who, body);
  thread.append(item);
  renderHomeThread();
  renderCoachCard();
}

function renderHomeThread() {
  const box = document.getElementById('home-thread');
  if (!box) return;
  box.replaceChildren(...[...thread.children].map((item) => item.cloneNode(true)));
}

function resetConversation(opening) {
  thread.replaceChildren();
  pushMessage('coach', opening);
}

function fillPlan(items) {
  const previous = new Map(planItems.map((item) => [item.title, item.done]));
  planItems = items.map((item) => ({...item, done: previous.get(item.title) || false}));
  renderPlanList();
}

function planVisibleItems() {
  if (planTab !== 'exercises') return planItems;
  return planItems.filter((item) => /drill|practice|rehears|exercise|\bsets?\b|\breps?\b|\brepetitions?\b/i.test(`${item.title} ${item.body || ''}`));
}

function planCopy(titleText, bodyText) {
  const copy = document.createElement('div');
  const title = document.createElement('p');
  title.className = 'plan-title';
  title.textContent = titleText;
  copy.append(title);
  if (bodyText) {
    const body = document.createElement('p');
    body.className = 'plan-body';
    body.textContent = bodyText;
    copy.append(body);
  }
  return copy;
}

function renderPlanList() {
  const items = planVisibleItems();
  planList.replaceChildren();
  const account = currentAccount();
  const role = account && account.activeRole === 'coach' ? 'coach' : 'skater';
  planEmpty.hidden = true;
  if (!items.length && planTab === 'exercises' && planItems.length) {
    planEmpty.textContent = 'The note does not name an exercise.';
  } else if (!items.length) {
    planEmpty.textContent = role === 'coach'
      ? 'Student progress appears from a lesson.'
      : 'The plan is written from the clip.';
  }
  if (!items.length) {
    const row = document.createElement('li');
    row.className = 'check-row';
    const mark = document.createElement('span');
    mark.className = 'check';
    mark.setAttribute('aria-hidden', 'true');
    row.append(mark, planCopy(planEmpty.textContent, ''));
    planList.append(row);
    renderPlanSummary();
    return;
  }
  let markedNext = false;
  items.forEach((item) => {
    const row = document.createElement('li');
    row.className = 'check-row';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'check';
    const next = !item.done && !markedNext;
    if (next) {
      markedNext = true;
      toggle.classList.add('is-next');
    }
    toggle.setAttribute('aria-pressed', item.done ? 'true' : 'false');
    toggle.setAttribute('aria-label', item.done ? 'Completed' : 'Mark done');
    toggle.textContent = item.done ? '✓' : '';
    toggle.addEventListener('click', () => {
      item.done = !item.done;
      renderPlanList();
    });
    const dose = `${item.title} ${item.body || ''}`.match(/\d+\s*(?:sets?|reps?|repetitions?)/gi);
    const extra = (dose || []).filter((part) => !item.title.includes(part) && !(item.body || '').includes(part));
    const body = [item.body, extra.join(' · ')].filter(Boolean).join(' ');
    row.append(toggle, planCopy(item.title, body));
    planList.append(row);
  });
  renderPlanSummary();
}

function answer(question) {
  const pool = [];
  coaching.cues.forEach((item) => {
    if (item.observation) pool.push(item.observation);
    if (item.advice) pool.push(item.advice);
    if (item.cue) pool.push(item.cue);
  });
  coaching.paragraphs.forEach((part) => pool.push(part));
  if (!pool.length) return 'Read the clip first. I will stay with what it shows.';
  const skip = new Set(['what', 'when', 'where', 'this', 'that', 'with', 'have', 'about', 'from', 'your', 'does', 'clip', 'spin', 'look', 'like', 'tell', 'should']);
  const keys = (question.toLowerCase().match(/[a-z]{4,}/g) || []).filter((word) => !skip.has(word));
  let best = '';
  let score = 0;
  pool.forEach((text) => {
    const hay = text.toLowerCase();
    const next = keys.reduce((total, word) => total + (hay.includes(word) ? 1 : 0), 0);
    if (next > score) {
      score = next;
      best = text;
    }
  });
  if (best) return best;
  return coaching.paragraphs.find((part) => /priorit|next attempt|practice|rehears/i.test(part)) || pool[0];
}

function sendChat(question) {
  const text = question.trim();
  if (!text) return false;
  pushMessage('user', text);
  pushMessage('coach', answer(text));
  return true;
}

function bindChat(formId, inputId) {
  document.getElementById(formId).addEventListener('submit', (event) => {
    event.preventDefault();
    const input = document.getElementById(inputId);
    if (!sendChat(input.value)) return;
    input.value = '';
    if (formId === 'chat-form') thread.parentElement.scrollIntoView({block: 'end'});
  });
}

bindChat('chat-form', 'chat-input');
bindChat('plan-chat-form', 'plan-chat-input');
bindChat('home-chat-form', 'home-chat-input');

reportToggle.addEventListener('click', () => {
  report.hidden = !report.hidden;
  reportToggle.textContent = report.hidden ? 'Full note' : 'Hide note';
});

document.getElementById('another').addEventListener('click', () => fileInput.click());

function presentReport(text) {
  coaching = parseReport(text);
  report.textContent = text;
  const impression = coaching.paragraphs[0] || coaching.cues[0]?.observation || '';
  if (impression) {
    homeLine.textContent = firstSentence(impression);
    homeLine.classList.add('is-note');
  }
  renderFeedback();
  renderAi();
  buildFrames();
  resetConversation(impression ? firstSentence(impression) : 'I have the clip.');
  const plan = [];
  coaching.cues.forEach((item) => {
    if (!item.advice) return;
    const title = firstSentence(item.advice);
    const rest = item.advice.replace(title, '').trim();
    plan.push({title, body: rest});
  });
  coaching.paragraphs.forEach((part) => {
    if (/^(observation|advice|cue|caption|measured evidence|#)/i.test(part)) return;
    if (!/priorit|next attempt|practice|rehears/i.test(part)) return;
    const title = firstSentence(part);
    plan.push({title, body: part.replace(title, '').trim()});
  });
  const seen = new Set();
  fillPlan(plan.filter((item) => {
    if (seen.has(item.title)) return false;
    seen.add(item.title);
    return true;
  }));
}

function showFeedback(files) {
  if (!previewUrl) {
    colorSamples = [];
    lastColorAt = -1;
    stage.src = files['feedback.mp4'];
    stage.muted = true;
    stage.loop = true;
    stage.load();
    stage.play().catch(() => {});
    document.body.classList.add('has-clip');
  }
  document.body.classList.add('done');
  document.body.classList.remove('working');
}

async function poll(url) {
  try {
    const response = await fetch(url);
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || 'Could not read job status.');
    if (job.status === 'failed') {
      pendingStatusUrl = null;
      document.body.classList.remove('working');
      throw new Error(job.error);
    }
    if (job.status !== 'completed') {
      statusText.textContent = job.stage;
      setTimeout(() => poll(url), 1000);
      return;
    }
    statusText.textContent = '';
    const files = job.files;
    showFeedback(files);
    document.getElementById('download-video').href = files['feedback.mp4'] + '?download=1';
    document.getElementById('download-report').href = files['coaching_report.md'] + '?download=1';
    document.getElementById('download-data').href = files['analysis.json'];
    presentReport(job.report || '');
    document.getElementById('provenance').textContent = job.generator
      ? `${job.generator}${job.model ? ' · ' + job.model : ''}`
      : '';
    document.getElementById('warning').textContent = job.warning || '';
    document.getElementById('results').hidden = false;
    pendingStatusUrl = null;
    button.disabled = false;
    button.textContent = readLabel();
    showScreen('analysis');
  } catch (error) {
    statusText.textContent = error.message;
    document.body.classList.remove('working');
    button.disabled = false;
    button.textContent = pendingStatusUrl ? 'Check again' : readLabel();
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!fileInput.files || !fileInput.files[0]) {
    statusText.textContent = 'Choose a clip first.';
    showScreen('home');
    return;
  }
  button.disabled = true;
  showScreen('analysis');
  if (pendingStatusUrl) {
    document.body.classList.add('working');
    await poll(pendingStatusUrl);
    return;
  }
  document.getElementById('results').hidden = true;
  document.body.classList.add('working');
  statusText.textContent = 'Sending the clip';
  button.textContent = 'Reading';
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
    document.body.classList.remove('working');
    button.disabled = false;
    button.textContent = readLabel();
  }
});

function readLabel() {
  const account = currentAccount();
  return account && account.activeRole === 'coach' ? 'Read this lesson' : 'Read this clip';
}

function loadStore() {
  try {
    return JSON.parse(localStorage.getItem('with.profile')) || {accounts: [], sessionId: null};
  } catch (error) {
    return {accounts: [], sessionId: null};
  }
}

function saveStore(store) {
  localStorage.setItem('with.profile', JSON.stringify(store));
}

function currentAccount() {
  const store = loadStore();
  return store.accounts.find((account) => account.id === store.sessionId) || null;
}

function updateAccount(patch) {
  const store = loadStore();
  const account = store.accounts.find((item) => item.id === store.sessionId);
  if (!account) return null;
  Object.assign(account, patch);
  saveStore(store);
  return account;
}

let chosenRole = 'skater';
let authMode = 'create';

function greeting() {
  const hour = new Date().getHours();
  const part = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const account = currentAccount();
  return account && account.name ? `${part}, ${account.name}` : part;
}

function formatDay(date) {
  return date.toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'});
}

function formatWhen(date) {
  const time = date.toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'});
  return `${formatDay(date)} · ${time}`;
}

function renderRecent() {
  const clip = document.body.classList.contains('has-clip');
  document.getElementById('session-date').textContent = clipWhen ? formatWhen(clipWhen) : '';
  if (clip) {
    document.getElementById('recent-name').textContent = sessionTitle.textContent;
    const bits = [];
    if (clipWhen) bits.push(formatDay(clipWhen));
    if (Number.isFinite(stage.duration) && stage.duration > 0) bits.push(fmt(stage.duration));
    document.getElementById('recent-meta').textContent = bits.join(' · ');
  }
  applyPanes();
}

function setBar(fillId, ratio) {
  const fill = document.getElementById(fillId);
  if (!fill) return;
  const pct = Math.round(Math.max(0, Math.min(1, ratio)) * 100);
  fill.style.width = `${pct}%`;
  const bar = fill.parentElement;
  if (bar && bar.getAttribute('role') === 'progressbar') bar.setAttribute('aria-valuenow', String(pct));
}

function renderPlanSummary() {
  const done = planItems.filter((item) => item.done).length;
  const title = sessionTitle.textContent || 'Training Plan';
  const ratio = planItems.length ? done / planItems.length : 0;
  document.getElementById('plan-goal').textContent = title;
  document.getElementById('plan-card-title').textContent = title;
  const count = planItems.length ? `${done} of ${planItems.length}` : '';
  document.getElementById('plan-week').textContent = count;
  const progress = planItems.length ? `${done}/${planItems.length} completed` : '';
  document.getElementById('plan-progress').textContent = progress;
  document.getElementById('plan-card-progress').textContent = progress || planEmpty.textContent;
  setBar('plan-fill', ratio);
  setBar('plan-card-fill', ratio);
}

function renderCoachCard() {
  const last = [...thread.querySelectorAll('.msg.coach p')].pop();
  const text = last ? last.textContent : '';
  document.getElementById('coach-card-line').textContent = text;
  document.getElementById('plan-coach-line').textContent = text;
  const account = currentAccount();
  const role = account && account.activeRole === 'coach' ? 'coach' : 'skater';
  const kind = role === 'coach' ? 'skater' : 'coach';
  const person = ((account && account.connections) || []).find((item) => item.kind === kind);
  const avatar = document.getElementById('plan-coach-avatar');
  if (avatar) avatar.textContent = person && person.name ? person.name.trim().charAt(0).toUpperCase() : '';
}

function renderAi() {
  const lines = uniqueLines([
    ...coaching.paragraphs,
    ...coaching.cues.map((item) => item.observation || item.advice || item.cue)
  ]);
  const waiting = document.body.classList.contains('has-clip')
    ? 'The clip is here. Read it when you are ready.'
    : 'Read the clip to open a note.';
  const line = lines[0] || waiting;
  document.getElementById('ai-copy').textContent = line;
  const planAi = document.getElementById('plan-ai-line');
  if (planAi) planAi.textContent = line;
  const body = document.getElementById('ai-body');
  body.replaceChildren();
  lines.slice(1, 6).forEach((paragraphText) => {
    const paragraph = document.createElement('p');
    paragraph.textContent = paragraphText;
    body.append(paragraph);
  });
}

function applyHome() {
  const account = currentAccount();
  const role = account && account.activeRole === 'coach' ? 'coach' : 'skater';
  const clip = document.body.classList.contains('has-clip');
  if (!clip) {
    homeLine.textContent = 'for coaches and skaters.';
    homeLine.classList.remove('is-note');
    sessionTitle.textContent = role === 'coach' ? 'Lesson' : 'Spin';
  }
  document.getElementById('greet').textContent = greeting();
  const profile = document.getElementById('profile');
  profile.textContent = account && account.name ? account.name.trim().charAt(0).toUpperCase() : '';
  pick.textContent = clip
    ? 'Replace footage'
    : (role === 'coach' ? 'Upload a lesson recording' : 'Upload a video');
  if (!button.disabled) button.textContent = readLabel();
  document.getElementById('plan-card').dataset.home = role === 'coach' ? 'progress' : 'plan';
  document.getElementById('plan-card-action').textContent = role === 'coach' ? 'Review student progress' : 'View training plans';
  document.getElementById('review-feedback').hidden = role !== 'skater';
  document.getElementById('coach-hit').dataset.home = role === 'coach' ? 'skaters' : 'connect';
  document.getElementById('coach-card-kicker').textContent = role === 'coach' ? 'Skaters' : 'Chat with Coach';
  const coachActions = document.getElementById('coach-actions');
  coachActions.replaceChildren();
  const coachItems = role === 'coach'
    ? [['skaters', 'View connected skaters'], ['notes', 'Add coaching notes']]
    : [['connect', 'Connect with a coach']];
  coachItems.forEach(([id, label]) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'text-action';
    item.dataset.home = id;
    item.textContent = label;
    coachActions.append(item);
  });
  renderPeople();
  renderRecent();
  renderPlanList();
  renderCoachCard();
}

function renderPeople() {
  const account = currentAccount();
  const role = account && account.activeRole === 'coach' ? 'coach' : 'skater';
  const kind = role === 'coach' ? 'skater' : 'coach';
  document.getElementById('people-kicker').textContent = role === 'coach' ? 'Skaters' : 'Coach';
  document.getElementById('people-name').placeholder = role === 'coach' ? 'Skater name' : 'Coach name';
  const people = ((account && account.connections) || []).filter((person) => person.kind === kind);
  const list = document.getElementById('people-list');
  const empty = document.getElementById('people-empty');
  list.replaceChildren();
  empty.hidden = people.length > 0;
  empty.textContent = role === 'coach' ? 'No skaters connected.' : 'No coach connected.';
  people.forEach((person) => {
    const item = document.createElement('li');
    item.textContent = person.name;
    list.append(item);
  });
}

function renderRoleSettings() {
  const account = currentAccount();
  const box = document.getElementById('role-switches');
  const add = document.getElementById('add-role');
  box.replaceChildren();
  if (!account) return;
  account.roles.forEach((role) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.textContent = role === 'coach' ? 'Coach' : 'Skater';
    if (account.activeRole === role) item.setAttribute('aria-current', 'true');
    item.addEventListener('click', () => {
      updateAccount({activeRole: role});
      applyHome();
      renderRoleSettings();
    });
    box.append(item);
  });
  if (account.roles.length > 1) {
    add.hidden = true;
    return;
  }
  const missing = account.roles.includes('skater') ? 'coach' : 'skater';
  add.hidden = false;
  add.textContent = missing === 'coach' ? 'Add the coach role' : 'Add the skater role';
  add.onclick = () => {
    updateAccount({roles: account.roles.concat(missing), activeRole: missing});
    applyHome();
    renderRoleSettings();
  };
}

function enterApp() {
  document.documentElement.classList.remove('is-gate');
  applyHome();
  renderRoleSettings();
  const role = currentAccount() && currentAccount().activeRole;
  resetConversation(role === 'coach'
    ? 'Add a lesson, or a note for a skater.'
    : 'Add a clip. I will read it with you.');
  showScreen('home');
  const restoredJob = new URLSearchParams(location.search).get('job');
  if (restoredJob && /^[a-f0-9]{32}$/.test(restoredJob) && !pendingStatusUrl) {
    pendingStatusUrl = `/api/jobs/${restoredJob}`;
    button.disabled = true;
    document.body.classList.add('working');
    showScreen('playback');
    poll(pendingStatusUrl);
  }
}

document.getElementById('home').addEventListener('click', (event) => {
  const source = event.target.closest('[data-home]');
  const id = source && source.dataset.home;
  if (id === 'plan' || id === 'progress') showScreen('plan');
  if (id === 'feedback') showScreen('analysis');
  if (id === 'connect' || id === 'skaters' || id === 'notes') showScreen('coach');
});

document.getElementById('open-session').addEventListener('click', () => {
  if (document.body.classList.contains('has-clip')) showScreen('playback');
});

document.getElementById('back').addEventListener('click', () => {
  const screen = document.body.dataset.screen;
  if (screen === 'analysis' && document.body.classList.contains('has-clip')) showScreen('playback');
  else if (screen === 'coach') showScreen('plan');
  else showScreen('home');
});

document.getElementById('profile').addEventListener('click', () => {
  document.getElementById('settings').hidden = false;
  showScreen('home');
});

document.getElementById('ai-toggle').addEventListener('click', () => {
  const body = document.getElementById('ai-body');
  const open = body.hidden;
  body.hidden = !open;
  document.getElementById('ai-toggle').setAttribute('aria-expanded', String(open));
});

document.querySelectorAll('[data-plan-tab]').forEach((tab) => {
  tab.addEventListener('click', () => {
    planTab = tab.dataset.planTab;
    document.querySelectorAll('[data-plan-tab]').forEach((item) => {
      item.setAttribute('aria-selected', item === tab ? 'true' : 'false');
    });
    renderPlanList();
  });
});

document.querySelectorAll('#role [data-role]').forEach((item) => {
  item.addEventListener('click', () => {
    chosenRole = item.dataset.role;
    authMode = 'create';
    document.getElementById('auth-line').textContent = 'Create an account';
    document.getElementById('auth-submit').textContent = 'Create account';
    document.getElementById('auth-switch').textContent = 'Log in';
    document.getElementById('auth-error').textContent = '';
    showScreen('auth');
  });
});

document.getElementById('auth-switch').addEventListener('click', () => {
  authMode = authMode === 'create' ? 'login' : 'create';
  const creating = authMode === 'create';
  document.getElementById('auth-line').textContent = creating ? 'Create an account' : 'Log in';
  document.getElementById('auth-submit').textContent = creating ? 'Create account' : 'Log in';
  document.getElementById('auth-switch').textContent = creating ? 'Log in' : 'Create an account';
  document.getElementById('auth-error').textContent = '';
});

document.getElementById('auth-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const name = document.getElementById('auth-name').value.trim();
  const pass = document.getElementById('auth-pass').value;
  const error = document.getElementById('auth-error');
  if (!name || !pass) {
    error.textContent = 'Add a name and a passphrase.';
    return;
  }
  const store = loadStore();
  const existing = store.accounts.find((account) => account.name.toLowerCase() === name.toLowerCase());
  if (authMode === 'create') {
    if (existing) {
      error.textContent = 'That name is already on this device. Log in.';
      return;
    }
    const account = {
      id: (crypto.randomUUID && crypto.randomUUID()) || String(Date.now()),
      name,
      pass,
      roles: [chosenRole],
      activeRole: chosenRole,
      connections: []
    };
    store.accounts.push(account);
    store.sessionId = account.id;
  } else {
    if (!existing || existing.pass !== pass) {
      error.textContent = 'That name or passphrase does not match.';
      return;
    }
    store.sessionId = existing.id;
  }
  saveStore(store);
  document.getElementById('auth-pass').value = '';
  error.textContent = '';
  enterApp();
});

document.getElementById('people-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const account = currentAccount();
  const input = document.getElementById('people-name');
  const name = input.value.trim();
  if (!account || !name) return;
  const kind = account.activeRole === 'coach' ? 'skater' : 'coach';
  const connections = (account.connections || []).concat({name, kind});
  updateAccount({connections});
  input.value = '';
  renderPeople();
});

document.getElementById('logout').addEventListener('click', () => {
  const store = loadStore();
  store.sessionId = null;
  saveStore(store);
  document.getElementById('settings').hidden = true;
  document.documentElement.classList.add('is-gate');
  showScreen('role');
});

resetConversation('Add a clip. I will read it with you.');
fillPlan([]);

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const returning = Boolean(currentAccount());
window.setTimeout(() => {
  if (returning) enterApp();
  else {
    showScreen('role');
    document.documentElement.classList.add('is-gate');
  }
  document.documentElement.classList.remove('is-still');
}, reduceMotion ? 0 : (returning ? 280 : 1100));
