import { acknowledgementReaction } from './coach-reactions.mjs'
import { SMS_HELP, smsText } from './training-coach.mjs'

export function createPhotonHandler({ allowedSender, delivery, answer, reset, send, platform = 'imessage', memory, agentId, react, withActivity = async (_message, work) => work() }) {
  const seen = new Set()
  const pausedChats = new Set()
  return async function handle(message) {
    if (seen.has(message.id)) return
    if (message.platform !== platform || message.sentBy?.handle !== allowedSender || message.space?.kind !== 'direct' || message.content?.type !== 'text') {
      seen.add(message.id)
      return
    }
    const senderId = message.receivedBy?.id || message.addressedTo?.id
    if (!senderId) throw new Error('Incoming message has no receiving agent ID')
    if (agentId && senderId !== agentId) return
    const chat = message.space.id
    const text = message.content.text.trim()
    const command = text.replace(/^\//, '').toUpperCase()
    if (memory) await memory.set({ route: { platform, senderId, spaceId: chat } })
    let stored = await delivery.get(message.id)
    if (stored?.state === 'submitted') { seen.add(message.id); return }
    if (!stored) {
      let reply
      if (['STOP', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT'].includes(command)) {
        pausedChats.add(chat)
        if (memory) await memory.set({ paused: true, notifications: false })
        reply = 'AI replies stopped. Send /ai to restart.'
      } else if (['AI', 'START'].includes(command)) {
        if (command === 'AI') await reset()
        pausedChats.delete(chat)
        if (memory) await memory.set({ paused: false, ...(command === 'START' ? { notifications: true } : {}) })
        reply = command === 'START'
          ? 'Your skate coach is on, including a text when new feedback is ready. Text GOAL with your focus, PLAN for practice, or tell me how skating felt. STOP pauses texts. Feedback and questions go to OpenAI.'
          : 'Your figure skating coach is connected. Text PLAN, PROGRESS, or ask about your video. START enables new-report texts; STOP pauses texts.'
      } else if (['HELP', '?'].includes(command)) {
        reply = SMS_HELP
      } else {
        const profile = memory ? await memory.get() : null
        if (profile?.paused || pausedChats.has(chat)) { seen.add(message.id); return }
        const reaction = acknowledgementReaction(text)
        if (reaction && react && message.nativeMessageId) {
          await react(message, reaction)
          seen.add(message.id)
          return
        }
        reply = await withActivity(message, () => answer(text.slice(0, 8000), platform, message.id))
      }
      stored = await delivery.save(message.id, smsText(reply))
    }
    // Reuse the exact saved reply on retries; never regenerate a different body
    // under the same idempotency key.
    const sent = await send({ senderId, spaceId: chat, voiceEligible: !['STOP', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT', 'AI', 'START', 'HELP', '?'].includes(command), replyTo: message.nativeMessageId, content: { type: 'text', format: 'plain', text: stored.reply } },
      `dh26-coach-v2-${message.id}`)
    if (sent.status === 'failed') throw new Error('Photon reported send failure')
    await delivery.submitted(message.id)
    seen.add(message.id)
    console.log(`Report coach reply submitted to Photon (${sent.status || 'accepted'}).`)
  }
}
