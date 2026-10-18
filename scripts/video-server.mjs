import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const root = fileURLToPath(new URL('../', import.meta.url))
const child = spawn(`${root}.video-venv/bin/python`, ['webapp.py', ...process.argv.slice(2)], {
  cwd: root, env: process.env, stdio: 'inherit',
})
child.on('error', () => { console.error('Could not start the Python video service. Complete the README Python setup first.'); process.exitCode = 1 })
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => child.kill(signal))
child.on('exit', code => { process.exitCode = code ?? 1 })
