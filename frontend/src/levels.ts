// Live audio levels for animations: `mic` while JARVIS listens, `out` while he speaks (0..1).
export const levels = { mic: 0, out: 0 }

let ctx: AudioContext | null = null
/** One shared AudioContext for analysing JARVIS's voice output. */
export function audioCtx(): AudioContext | null {
  try { ctx = ctx || new AudioContext() } catch { return null }
  return ctx
}

/** Route an <audio> element through an analyser so `levels.out` follows his voice. */
export async function trackOutput(el: HTMLAudioElement): Promise<() => void> {
  const c = audioCtx()
  if (!c) return () => {}
  if (c.state !== 'running') { try { await c.resume() } catch { /* ignore */ } }
  if (c.state !== 'running') return () => {}   // never route audio into a muted context
  let src: MediaElementAudioSourceNode
  try { src = c.createMediaElementSource(el) } catch { return () => {} }
  const an = c.createAnalyser(); an.fftSize = 512
  src.connect(an); an.connect(c.destination)
  const buf = new Float32Array(an.fftSize)
  let raf = 0
  const loop = () => {
    an.getFloatTimeDomainData(buf)
    let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i]
    levels.out = Math.min(1, Math.sqrt(s / buf.length) * 4)
    raf = requestAnimationFrame(loop)
  }
  loop()
  return () => { cancelAnimationFrame(raf); levels.out = 0; try { src.disconnect(); an.disconnect() } catch { /* ignore */ } }
}
