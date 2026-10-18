export function createNativeGroupHandler({ studentHandle, agentId, platform = 'imessage', groupCapable,
  members, groups, delivery, send, react, withActivity = async (_message, work) => work() }) {
  const seen = new Set()
  return async message => {
    if (seen.has(message.id)) return
    if (message.platform !== platform || message.space?.kind !== 'group' || message.content?.type !== 'text') return
    if (!groupCapable()) return
    const participants = await members(message.space.id)
    if (participants.length < 2 || new Set(participants.map(member => member.id)).size !== participants.length) return
    if (participants.some(member => member.id !== agentId && member.kind !== 'human')) return
    const student = participants.find(member => member.handle === studentHandle && member.kind === 'human')
    const agent = participants.find(member => member.id === agentId && member.kind === 'agent')
    const sender = participants.find(member => member.id === message.sentBy.id && member.handle === message.sentBy.handle && member.kind === 'human')
    if (!student || !agent || !sender) return
    const boundMembers = participants.map(member => ({ id: member.id, role: member.id === agentId ? 'ai' : 'member' }))
    let stored = await delivery.get(message.id)
    if (stored?.state === 'submitted') { seen.add(message.id); return }
    if (!stored) {
      const result = await groups.native(message, boundMembers, work => withActivity(message, work))
      if (result.reaction && react && message.nativeMessageId) await react(message, result.reaction)
      if (!result.replied) { seen.add(message.id); return }
      stored = await delivery.save(message.id, result.reply)
    }
    const result = await send({ senderId: agentId, spaceId: message.space.id, voiceEligible: !/^(?:ai[, :]*)?\/?help[!.?]*$/i.test(message.content.text.trim()), replyTo: message.nativeMessageId,
      content: { type: 'text', format: 'plain', text: stored.reply } }, `dh26-coach-v2-${message.id}`)
    if (result.status === 'failed') throw new Error('Photon group reply failed')
    await delivery.submitted(message.id)
    seen.add(message.id)
  }
}
