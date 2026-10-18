// Only invoked for an authorized, unpaused direct question needing a new answer.
export function createMessageActivity({ authorize, chats, refreshMs = 8000 }) {
  return async (message, work) => {
    const chat = message.space.id
    await authorize(chat)
    const bestEffort = async action => { try { await action() } catch { /* Cosmetic API failure. */ } }
    await bestEffort(() => chats.markRead(chat))
    await bestEffort(() => chats.setTyping(chat, true))
    let pending = null
    const timer = setInterval(() => {
      if (pending) return
      pending = bestEffort(async () => {
        await authorize(chat)
        await chats.setTyping(chat, true)
      }).finally(() => { pending = null })
    }, refreshMs)
    timer.unref?.()
    try { return await work() }
    finally {
      clearInterval(timer)
      await pending
      await bestEffort(() => chats.setTyping(chat, false))
    }
  }
}
