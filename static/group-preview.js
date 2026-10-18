(() => {
  const roomSelect = document.getElementById('group-room');
  const status = document.getElementById('group-status');
  const send = document.getElementById('group-send');
  const form = document.getElementById('group-form');
  const text = document.getElementById('group-text');
  const newButton = document.getElementById('new-group');
  let pending = null;

  async function api(path = '', payload) {
    const response = await fetch(`/api/coach/rooms${path}`, payload === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Group unavailable. Try again.');
    return data;
  }
  function render(room) {
    const messages = document.getElementById('group-messages');
    messages.replaceChildren();
    for (const message of room.messages || []) {
      const item = document.createElement('li');
      item.className = message.role;
      const label = document.createElement('strong');
      label.textContent = message.role === 'ai' ? 'Skating AI' : 'Participant';
      item.append(label, document.createTextNode(`\n${message.text}`));
      messages.append(item);
    }
    messages.scrollTop = messages.scrollHeight;
    status.textContent = `${room.muted ? 'AI is muted.' : 'AI replies when invited with “AI,”.'}`;
  }
  async function selectRoom() {
    pending = null;
    send.disabled = true;
    if (!roomSelect.value) return;
    try { render(await api(`/${roomSelect.value}`)); send.disabled = false; }
    catch (error) { status.textContent = error.message; }
  }
  async function loadRooms(preferred) {
    const data = await api();
    roomSelect.replaceChildren();
    const rooms = data.rooms.filter(room => room.mode === 'preview');
    for (const room of rooms) {
      const option = document.createElement('option');
      option.value = room.id;
      option.textContent = `${room.name} · ${new Date(room.createdAt).toLocaleString()}`;
      roomSelect.append(option);
    }
    if (preferred) roomSelect.value = preferred;
    if (!rooms.length) status.textContent = 'Create a preview to try the conversation.';
    await selectRoom();
  }
  roomSelect.addEventListener('change', selectRoom);
  newButton.addEventListener('click', async () => {
    newButton.disabled = true;
    try { const room = await api('', { name: 'Skating group + AI' }); await loadRooms(room.id); }
    catch (error) { status.textContent = error.message; }
    finally { newButton.disabled = false; }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const roomId = roomSelect.value;
    if (!roomId || !text.value.trim()) return;
    const role = 'member';
    const participantId = document.getElementById('group-role').value;
    if (!pending || pending.text !== text.value.trim() || pending.participantId !== participantId) {
      pending = { id: crypto.randomUUID(), role, participantId, text: text.value.trim() };
    }
    send.disabled = newButton.disabled = roomSelect.disabled = true;
    status.textContent = 'Sending…';
    try {
      const result = await api(`/${roomId}/messages`, pending);
      render(result.room);
      text.value = '';
      pending = null;
    } catch (error) { status.textContent = `${error.message} Retry to resend the same message.`; }
    finally { send.disabled = newButton.disabled = roomSelect.disabled = false; }
  });
  fetch('/api/text-coach').then(response => response.json()).then(data => {
    document.getElementById('group-line-status').textContent = data.groupChatReady
      ? `Group delivery available on ${data.number}. Everyone in your group can ask the AI.`
      : `${data.number || 'Photon line'}: ${data.groupChatReason || data.reason || 'checking connection'}. Local preview is available below.`;
  }).catch(() => { document.getElementById('group-line-status').textContent = 'Phone connection unavailable. Local preview requires the coach service.'; });
  loadRooms().catch(error => { status.textContent = error.message; });
})();
