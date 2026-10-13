// Speaks a reply sentence by sentence *while it is still being written*: the first sentence is
// sent to ElevenLabs as soon as it's complete and starts playing while later ones are fetched.
// This is what makes JARVIS start talking in about a second instead of after the whole answer.
import { synthesize } from './api'
import { trackOutput } from './levels'

const clean = (t: string) => t.replace(/```[\s\S]*?```/g, ' ').replace(/https?:\/\/\S+/g, 'the link')
  .replace(/[*_#>`|]/g, '').replace(/\s+/g, ' ').trim()

export class SpeechQueue {
  private buf = ''
  private parts: Promise<string | null>[] = []
  private playing = false
  private ended = false
  private cancelled = false
  private audio: HTMLAudioElement | null = null
  private aborts: AbortController[] = []
  private resolveDone: (() => void) | null = null
  private done: Promise<void>
  private started = false
  private queued = 0
  private onStart: () => void
  private onError: (m: string) => void

  constructor(onStart: () => void = () => {}, onError: (m: string) => void = () => {}) {
    this.onStart = onStart; this.onError = onError
    this.done = new Promise(r => { this.resolveDone = r })
  }

  /** Add streamed text; complete sentences are queued for speech right away. */
  feed(delta: string) {
    if (this.cancelled) return
    this.buf += delta
    for (;;) {
      // a sentence end, or a comma/colon once there's a decent amount buffered (keeps the first chunk quick)
      const m = this.buf.match(/^([\s\S]*?[.!?…](?:["')\]]*)(?:\s|$))/) ||
        (this.buf.length > 140 ? this.buf.match(/^([\s\S]{60,}?[,;:])\s/) : null) ||
        this.buf.match(/^([\s\S]*?)\n\s*\n/)
      if (!m) break
      this.buf = this.buf.slice(m[0].length)
      this.push(m[1])
    }
  }

  /** The reply is complete: speak whatever is left. */
  end() {
    if (this.buf.trim()) this.push(this.buf)
    this.buf = ''
    this.ended = true
    this.pump()
  }

  /** Resolves when everything has been spoken (or cancelled). */
  wait() { return this.done }
  get hasSpeech() { return this.queued > 0 }

  cancel() {
    this.cancelled = true
    this.aborts.forEach(a => a.abort())
    if (this.audio) { this.audio.pause(); this.audio.onended?.(new Event('ended')) }
    this.finish()
  }

  private push(text: string) {
    const t = clean(text)
    if (!t || !/[\p{L}\p{N}]/u.test(t)) return
    const ac = new AbortController()
    this.aborts.push(ac)
    this.queued++
    this.parts.push(synthesize(t, ac.signal).catch(e => {
      if ((e as Error).name !== 'AbortError') this.onError((e as Error).message)
      return null
    }))
    this.pump()
  }

  private async pump() {
    if (this.playing || this.cancelled) return
    this.playing = true
    while (this.parts.length && !this.cancelled) {
      const url = await this.parts.shift()!
      if (!url || this.cancelled) continue
      if (!this.started) { this.started = true; this.onStart() }
      await new Promise<void>(resolve => {
        const a = new Audio(url)
        this.audio = a
        let untrack = () => {}
        const finish = () => { untrack(); URL.revokeObjectURL(url); if (this.audio === a) this.audio = null; resolve() }
        a.onended = finish; a.onerror = finish
        trackOutput(a).then(u => { untrack = u; return a.play() }).catch(finish)
      })
    }
    this.playing = false
    if (this.ended && !this.parts.length) this.finish()
  }

  private finish() { this.resolveDone?.(); this.resolveDone = null }
}
