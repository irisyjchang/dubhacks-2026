import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { callSetupPayloads, createCallGateway, createElevenLabsApi, placeCoachCall, hostedAgentConfig, createHostedCallSync, groupCallersFromChat, sipCallerFormats } from './photon-calls.mjs'

const env = { PHOTON_PHONE_NUMBER: '+16285027257', PHOTON_ALLOWED_SENDER: '+19054629158',
  SPECTRUM_PROJECT_ID: 'project', SPECTRUM_PROJECT_SECRET: 'secret' }
const token = 'a'.repeat(64)

test('SIP caller variants represent only the approved numbers', () => {
  assert.deepEqual(sipCallerFormats(['+12062457436']), ['+12062457436', '12062457436', '2062457436'])
  assert.deepEqual(sipCallerFormats(['+442012345678']), ['+442012345678', '442012345678'])
  assert.equal(sipCallerFormats(['+12062457436', '+12062457436']).length, 3)
  assert.throws(() => sipCallerFormats(['anonymous']))
})

test('group calling includes current human phone numbers and rejects unrelated chats', () => {
  const chat = { guid: 'group', isGroup: true, participants: [
    { address: env.PHOTON_ALLOWED_SENDER }, { address: '+15555550123' },
    { address: env.PHOTON_PHONE_NUMBER }, { address: 'member@example.com' },
  ] }
  const options = { spaceId: 'group', number: env.PHOTON_PHONE_NUMBER, owner: env.PHOTON_ALLOWED_SENDER }
  assert.deepEqual(groupCallersFromChat(chat, options), ['+15555550123', env.PHOTON_ALLOWED_SENDER])
  assert.throws(() => groupCallersFromChat({ ...chat, isGroup: false }, options))
  assert.throws(() => groupCallersFromChat({ ...chat, participants: [{ address: '+15555550123' }] }, options))
  assert.throws(() => groupCallersFromChat(chat, { ...options, spaceId: 'different' }))
})

test('SIP setup uses stable Photon TLS, compatible RTP, and system-supplied identities', () => {
  const payloads = callSetupPayloads(env, 'https://voice.example.com', token)
  assert.equal(payloads.phone.outbound_trunk_config.address, 'sip.spectrum.photon.codes:5061')
  assert.equal(payloads.phone.outbound_trunk_config.transport, 'tls')
  assert.equal(payloads.agent.conversation_config.tts.model_id, 'eleven_flash_v2')
  assert.equal(payloads.phone.outbound_trunk_config.media_encryption, 'disabled')
  assert.deepEqual(payloads.phone.inbound_trunk_config.allowed_numbers, [env.PHOTON_ALLOWED_SENDER])
  const properties = payloads.tool.tool_config.api_schema.request_body_schema.properties
  assert.equal(properties.caller.dynamic_variable, 'system__caller_id')
  assert.equal(properties.caller.description, undefined, 'LLM cannot select a caller identity')
  assert.equal(properties.called.dynamic_variable, 'system__called_number')
  assert.equal(payloads.inboundUri, 'sips:+16285027257@sip.rtc.elevenlabs.io:5061')
  assert.throws(() => callSetupPayloads(env, 'http://voice.example.com', token), /HTTPS/)
})

test('call gateway rejects unauthorized callers and paused coaching; both call directions share memory', async () => {
  let paused = false, answers = 0
  const server = createCallGateway({ token, number: env.PHOTON_PHONE_NUMBER, owner: env.PHOTON_ALLOWED_SENDER,
    memory: { get: async () => ({ paused }) }, answer: async (question, channel) => {
      answers++; assert.equal(channel, 'voice-call'); return `Saved feedback: ${question}`
    } })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const url = `http://127.0.0.1:${server.address().port}/api/calls/coach`
  const input = { caller: env.PHOTON_ALLOWED_SENDER, called: env.PHOTON_PHONE_NUMBER,
    conversationId: 'conv_test', turn: '1', question: 'How was my spin?' }
  const post = (value = input, auth = `Bearer ${token}`, path = url) => fetch(path, { method: 'POST',
    headers: { Authorization: auth, 'Content-Type': 'application/json' }, body: JSON.stringify(value) })
  try {
    assert.equal((await post(input, '')).status, 401)
    assert.equal((await post({ ...input, caller: '+15555550123' })).status, 403)
    assert.equal((await post(input, `Bearer ${token}`, url.replace('/calls/coach', '/coach/analysis'))).status, 404)
    assert.equal(answers, 0)
    const [first, duplicate] = await Promise.all([post(), post()])
    assert.equal(first.status, 200)
    assert.deepEqual(await first.json(), await duplicate.json())
    assert.equal(answers, 1)
    assert.equal((await post({ ...input, caller: input.called, called: input.caller, turn: 2 })).status, 200)
    assert.equal(answers, 2)
    paused = true
    assert.equal((await post()).status, 403, 'STOP is checked even for cached answers')
    assert.equal((await post({ ...input, question: '' })).status, 400)
    assert.equal((await post({ ...input, question: 'x'.repeat(17000) })).status, 413)
  } finally { await new Promise(resolve => server.close(resolve)) }
})

test('outbound calls target only the configured owner; uncertain submissions never dial twice', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'photon-calls-'))
  const config = { agentId: 'agent', phoneNumberId: 'phone', number: env.PHOTON_PHONE_NUMBER, owner: env.PHOTON_ALLOWED_SENDER }
  let requests = 0
  const api = async (path, body) => {
    requests++; assert.equal(path, '/sip-trunk/outbound-call')
    assert.equal(body.to_number, env.PHOTON_ALLOWED_SENDER)
    throw new Error('Network timeout after provider accepted call')
  }
  try {
    const args = { env, config, directory, api, requestId: 'same-user-request' }
    await assert.rejects(placeCoachCall(args), /Network timeout/)
    assert.deepEqual(await placeCoachCall(args), { duplicate: true })
    assert.equal(requests, 1)
    await assert.rejects(placeCoachCall({ ...args, config: { ...config, number: '+15555550123' } }), /setup/)
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test('provider failures never echo credentials into errors', async () => {
  const api = createElevenLabsApi({ env: { ELEVENLABS_API_KEY: 'secret' }, fetchImpl: async () => ({
    ok: false, status: 403, json: async () => ({ error: 'secret' }),
  }) })
  await assert.rejects(api('/tools', {}), { message: 'ElevenLabs request failed (403)' })
})

test('hosted mode needs no URL or webhook and carries saved feedback without promising writes', () => {
  const agent = hostedAgentConfig({ env, instructions: 'Saved feedback at 2s: reach forward.', history: [{ role: 'user', content: 'Review my arms' }] })
  assert.deepEqual(agent.conversation_config.agent.prompt.tool_ids, [])
  assert.equal(agent.platform_settings.auth.enable_auth, true)
  assert.match(agent.conversation_config.agent.prompt.prompt, /reach forward/)
  assert.match(agent.conversation_config.agent.prompt.prompt, /Review my arms/)
  assert.match(agent.conversation_config.agent.prompt.prompt, /cannot fetch new data or save/)
  assert.doesNotMatch(agent.conversation_config.agent.prompt.prompt, /ask_skating_coach/)
  const paused = hostedAgentConfig({ env, instructions: 'PRIVATE', history: ['PRIVATE'], paused: true })
  assert.doesNotMatch(JSON.stringify(paused), /PRIVATE/)
  assert.match(paused.conversation_config.agent.first_message, /paused/)
})

test('hosted sync updates changed context, detaches paused calls, and retries failed updates', async () => {
  let snapshot = { instructions: 'Feedback one', history: [], paused: false }, fail = false
  const requests = []
  const sync = createHostedCallSync({ config: { agentId: 'agent', phoneNumberId: 'phone' }, env,
    context: async () => snapshot, api: async (path, body, method) => {
      if (fail) { fail = false; throw new Error('temporary failure') }
      requests.push({ path, body, method })
    } })
  assert.equal((await sync()).ready, true)
  assert.equal(requests.length, 2)
  await sync()
  assert.equal(requests.length, 2, 'unchanged context does not create new agent versions')
  snapshot = { ...snapshot, instructions: 'Feedback two' }
  fail = true
  await assert.rejects(sync(), /temporary failure/)
  await sync()
  assert.equal(requests.length, 3)
  snapshot = { ...snapshot, paused: true }
  assert.equal((await sync()).ready, false)
  assert.deepEqual(requests.at(-1).body, { agent_id: null })
  assert.doesNotMatch(JSON.stringify(requests.at(-2)), /Feedback two/)
  snapshot = { ...snapshot, paused: false }
  await sync()
  assert.deepEqual(requests.at(-1).body, { agent_id: 'agent' })
})
