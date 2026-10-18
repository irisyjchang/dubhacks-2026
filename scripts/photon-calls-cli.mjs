import { randomBytes, randomUUID } from 'node:crypto'
import { mkdir, writeFile, rename } from 'node:fs/promises'
import { join } from 'node:path'
import { callDirectory, readCallConfig, callSetupPayloads, createElevenLabsApi, placeCoachCall, hostedAgentConfig, groupCallersFromChat, sipCallerFormats } from './photon-calls.mjs'
import { cloud } from 'spectrum-ts'
import { createGrpcClient } from '@photon-ai/advanced-imessage/grpc'
import { canonicalHandle } from './spectrum-adapter.mjs'
import { openCoachDatabase } from './coach-database.mjs'
import { coachInstructions } from './coach-state.mjs'

const command = process.argv[2] || 'plan'
try {
  const env = process.env
  const directory = callDirectory()
  const saved = await readCallConfig(directory)
  if (command === 'allow-group') {
    if (saved?.mode !== 'hosted' || !saved?.agentId || !saved?.phoneNumberId) throw new Error('Set up hosted calling first')
    const number = canonicalHandle(env.PHOTON_PHONE_NUMBER), owner = canonicalHandle(env.PHOTON_ALLOWED_SENDER)
    if (saved.number !== number || saved.owner !== owner) throw new Error('Call configuration belongs to another line')
    const database = await openCoachDatabase()
    let remote
    try {
      const profile = await database.athlete()
      const route = profile.groupRoute
      if (!route?.spaceId || route.agentId !== `spectrum:${number}`) throw new Error('No saved coaching group for this line')
      let chat
      if (process.argv.includes('--saved-roster')) {
        const room = await database.nativeRoom(route.spaceId)
        if (!room?.members?.length || room.platform !== 'imessage') throw new Error('No verified native iMessage roster saved for this group')
        chat = { guid: route.spaceId, isGroup: true,
          participants: room.members.filter(member => member.role !== 'ai').map(member => ({ address: member.id })) }
        console.log('Using the last saved native group roster; live Photon membership could not be checked.')
      } else {
        const tokens = await cloud.issueImessageTokens(env.SPECTRUM_PROJECT_ID, env.SPECTRUM_PROJECT_SECRET)
        const instance = Object.keys(tokens.numbers).find(key => canonicalHandle(tokens.numbers[key]) === number)
        if (tokens.type !== 'dedicated' || !instance) throw new Error('Configured dedicated Photon line unavailable')
        remote = createGrpcClient({ address: `${instance}.imsg.photon.codes:443`, tls: true, timeout: 30000, token: tokens.auth[instance] })
        chat = await remote.chats.get(route.spaceId)
      }
      const allowedCallers = groupCallersFromChat(chat, { spaceId: route.spaceId, number, owner })
      const allowedFormats = sipCallerFormats(allowedCallers)
      const api = createElevenLabsApi()
      // Replace private DM context with shared feedback before widening access.
      await api(`/agents/${encodeURIComponent(saved.agentId)}`, hostedAgentConfig({ env, paused: profile.paused,
        instructions: await coachInstructions({}, database), history: [] }), 'PATCH')
      await api(`/phone-numbers/${encodeURIComponent(saved.phoneNumberId)}`, {
        inbound_trunk_config: { allowed_numbers: allowedFormats, media_encryption: 'disabled' },
      }, 'PATCH')
      const verified = await api(`/phone-numbers/${encodeURIComponent(saved.phoneNumberId)}`, undefined, 'GET')
      if (JSON.stringify([...verified.inbound_trunk.allowed_numbers].sort()) !== JSON.stringify(allowedFormats)) throw new Error('Provider did not retain the group caller list')
      await writeFile(join(directory, 'config.tmp'), JSON.stringify({ ...saved, access: 'group', allowedCallers, groupSpaceId: route.spaceId }), { mode: 0o600 })
      await rename(join(directory, 'config.tmp'), join(directory, 'config.json'))
      console.log(`Verified inbound calling enabled for ${allowedCallers.length} group phone numbers. Private DM history is excluded from voice context. Restart the Photon listener to load the group access setting.`)
    } finally { await remote?.close(); await database.close() }
  } else if (command === 'dial') {
    const api = createElevenLabsApi()
    // Verify the imported trunk still points to our exact line and agent before dialling.
    if (!saved?.phoneNumberId) throw new Error('Run npm run calls:setup first')
    const phone = await api(`/phone-numbers/${encodeURIComponent(saved.phoneNumberId)}`, undefined, 'GET')
    if (phone.phone_number !== saved.number || phone.assigned_agent?.agent_id !== saved.agentId || phone.provider !== 'sip_trunk') throw new Error('The call trunk assignment has changed')
    const status = await fetch('http://127.0.0.1:8787/api/coach/messaging', { signal: AbortSignal.timeout(5000) })
    if (!status.ok) throw new Error('Start the coach listener before requesting a call')
    const state = await status.json()
    if (state.paused || !(state.calling?.ready || state.calling?.gatewayReady)) throw new Error('Enable calling and send START before requesting a call')
    const result = await placeCoachCall({ requestId: process.argv[3] || randomUUID(), config: saved })
    console.log(result.duplicate ? 'This call request was already attempted. Check provider call history.' : 'Call submitted to the configured feedback owner.')
  } else if (command === 'plan' || command === 'setup') {
    const mode = env.PHOTON_CALLS_MODE || (env.CALLS_PUBLIC_URL ? 'webhook' : 'hosted')
    if (!['hosted', 'webhook'].includes(mode)) throw new Error('PHOTON_CALLS_MODE must be hosted or webhook')
    const publicUrl = mode === 'webhook' ? env.CALLS_PUBLIC_URL : null
    if (mode === 'webhook' && !publicUrl) throw new Error('Webhook mode requires CALLS_PUBLIC_URL; use PHOTON_CALLS_MODE=hosted to call without a public HTTPS endpoint')
    const token = saved?.token || randomBytes(32).toString('hex')
    const payloads = callSetupPayloads(env, publicUrl, token)
    if (command === 'plan') {
      console.log(JSON.stringify({ connection: 'Photon Spectrum (stable) + ElevenLabs SIP',
        number: payloads.phone.phone_number, inboundUri: payloads.inboundUri,
        mode, webhook: payloads.tool.tool_config.api_schema.url, callbackRecipient: env.PHOTON_ALLOWED_SENDER,
        sip: { host: 'sip.spectrum.photon.codes', port: 5061, transport: 'tls', media: 'RTP', registration: false },
        configured: Boolean(saved?.agentId && saved?.phoneNumberId),
        next: 'Run calls:setup, register inboundUri in Photon, then enable PHOTON_CALLS_ENABLED=true. Hosted mode needs no public HTTPS endpoint.' }, null, 2))
    } else {
      const api = createElevenLabsApi()
      const config = saved || { token, number: payloads.phone.phone_number, owner: canonicalHandle(env.PHOTON_ALLOWED_SENDER) }
      if (config.number !== payloads.phone.phone_number || config.owner !== canonicalHandle(env.PHOTON_ALLOWED_SENDER)) throw new Error('Saved call configuration belongs to another line or owner')
      const save = async () => {
        await mkdir(directory, { recursive: true, mode: 0o700 })
        await writeFile(join(directory, 'config.tmp'), JSON.stringify(config), { mode: 0o600 })
        await rename(join(directory, 'config.tmp'), join(directory, 'config.json'))
      }
      await save()
      if (mode === 'webhook') {
        if (config.toolId) await api(`/tools/${encodeURIComponent(config.toolId)}`, payloads.tool, 'PATCH')
        else { config.toolId = (await api('/tools', payloads.tool)).id; await save() }
        payloads.agent.conversation_config.agent.prompt.tool_ids = [config.toolId]
      } else {
        const database = await openCoachDatabase()
        try {
          const profile = await database.athlete()
          const feedback = await database.latestFeedback()
          payloads.agent = hostedAgentConfig({ env, paused: profile.paused,
            instructions: await coachInstructions(config.access === 'group' ? {} : undefined, database),
            history: config.access === 'group' ? [] : await database.history(feedback?.id) })
        } finally { await database.close() }
      }
      if (config.agentId) await api(`/agents/${encodeURIComponent(config.agentId)}`, payloads.agent, 'PATCH')
      else { config.agentId = (await api('/agents/create', payloads.agent)).agent_id; await save() }
      if (!config.phoneNumberId) {
        const existing = await api('/phone-numbers', undefined, 'GET')
        if (existing.some(phone => phone.phone_number === config.number)) throw new Error('This number is already imported in ElevenLabs; inspect its existing assignment before changing it')
        config.phoneNumberId = (await api('/phone-numbers', { ...payloads.phone, agent_id: config.agentId })).phone_number_id
        await save()
      }
      if (config.allowedCallers?.length) await api(`/phone-numbers/${encodeURIComponent(config.phoneNumberId)}`, {
        inbound_trunk_config: { allowed_numbers: sipCallerFormats(config.allowedCallers), media_encryption: 'disabled' },
      }, 'PATCH')
      config.publicUrl = publicUrl
      config.mode = mode
      await save()
      console.log(`Voice agent and trunk configured. In Photon, register this inbound route for ${config.number}: ${payloads.inboundUri}`)
      console.log(`Mode: ${mode}. Enable PHOTON_CALLS_ENABLED=true and restart npm run photon. Verify inbound and outbound two-way audio before treating calls as live.`)
    }
  } else throw new Error('Use plan, setup, allow-group, or dial [stable-request-id]')
} catch (error) { console.error(error.message); process.exitCode = 1 }
