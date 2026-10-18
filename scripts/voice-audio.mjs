import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
const run = promisify(execFile)
let binary
export async function voiceFfmpeg() {
  if (process.env.FFMPEG_PATH) return process.env.FFMPEG_PATH
  if (!binary) binary = run(join(process.cwd(), '.video-venv', 'bin', 'python'),
    ['-c', 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'], { timeout: 10000 })
    .then(result => result.stdout.trim()).catch(() => 'ffmpeg')
  return binary
}
export async function encodeVoiceAudio(data) {
  const directory = await mkdtemp(join(tmpdir(), 'coach-audio-'))
  try {
    const input = join(directory, 'input.mp3'), output = join(directory, 'voice.m4a')
    await writeFile(input, data, { mode: 0o600 })
    const ffmpeg = await voiceFfmpeg()
    await run(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-y', '-i', input,
      '-vn', '-ac', '1', '-ar', '44100', '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', output], { timeout: 30000 })
    // Decode the complete file and verify the container has a positive duration.
    const check = await run(ffmpeg, ['-hide_banner', '-i', output, '-f', 'null', '-'], { timeout: 30000 })
    const duration = /Duration: (\d+):(\d+):(\d+(?:\.\d+)?)/.exec(check.stderr)
    if (!duration || Number(duration[1]) * 3600 + Number(duration[2]) * 60 + Number(duration[3]) <= 0) throw new Error('Voice audio has no duration')
    return new Uint8Array(await readFile(output))
  } finally { await rm(directory, { recursive: true, force: true }) }
}
