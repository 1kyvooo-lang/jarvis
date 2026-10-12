// Voice layer with swappable providers.
//   ElevenLabs (default): mic audio is recorded here, transcribed by Scribe via the backend,
//   and replies are spoken with an ElevenLabs voice streamed through the backend.
//   Browser (fallback when no ElevenLabs key): the built-in Web Speech APIs.
import { synthesize, transcribe } from './api'
import { trackOutput } from './levels'

export interface Listener {
  start(onPartial: (text: string) => void): Promise<void>
  /** Stop listening and resolve with the final transcript ('' if nothing was said). */
  stop(): Promise<string>
  cancel(): void
}

export interface Speaker {
  speak(text: string, onEnd: () => void): Promise<void>
  cancel(): void
}

const micError = (e: unknown) => {
  const name = (e as { name?: string })?.name
  if (name === 'NotAllowedError' || name === 'SecurityError')
    return 'Microphone access is blocked. Allow it for JARVIS in the browser, and in System Settings → Privacy & Security → Microphone.'
  if (name === 'NotFoundError') return 'No microphone was found.'
  return `Microphone error: ${(e as Error)?.message || e}`
}

/** Records audio and sends it to ElevenLabs Scribe when you stop. */
export class ElevenLabsListener implements Listener {
  private rec: MediaRecorder | null = null
  private chunks: Blob[] = []
  private stream: MediaStream | null = null
  private started = 0

  async start(onPartial: (t: string) => void) {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
    } catch (e) { throw new Error(micError(e)) }
    const mime = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find(m => MediaRecorder.isTypeSupported(m))
    this.chunks = []
    this.rec = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined)
    this.rec.ondataavailable = e => { if (e.data.size) this.chunks.push(e.data) }
    this.rec.start(250)
    this.started = Date.now()
    onPartial('Listening…')
  }

  stop(): Promise<string> {
    const rec = this.rec
    if (!rec) return Promise.resolve('')
    return new Promise((resolve, reject) => {
      rec.onstop = async () => {
        this.release()
        const blob = new Blob(this.chunks, { type: rec.mimeType || 'audio/webm' })
        if (Date.now() - this.started < 400 || blob.size < 1500) return resolve('')
        try { resolve(await transcribe(blob)) } catch (e) { reject(e) }
      }
      rec.stop()
    })
  }

  cancel() { if (this.rec && this.rec.state !== 'inactive') { this.rec.onstop = () => this.release(); this.rec.stop() } else this.release() }

  private release() { this.stream?.getTracks().forEach(t => t.stop()); this.stream = null; this.rec = null }
}

export class ElevenLabsSpeaker implements Speaker {
  private audio: HTMLAudioElement | null = null
  private abort: AbortController | null = null
  async speak(text: string, onEnd: () => void) {
    this.cancel()
    const clean = text.replace(/```[\s\S]*?```/g, ' ').replace(/[*_#>`]/g, '').trim()
    if (!clean) return onEnd()
    this.abort = new AbortController()
    const url = await synthesize(clean.slice(0, 4500), this.abort.signal)
    const a = new Audio(url)
    this.audio = a
    const untrack = await trackOutput(a)
    const done = () => { untrack(); URL.revokeObjectURL(url); if (this.audio === a) this.audio = null; onEnd() }
    a.onended = done
    a.onerror = done
    await a.play()
  }
  cancel() {
    this.abort?.abort(); this.abort = null
    if (this.audio) { this.audio.pause(); this.audio.onended?.(new Event('ended')); this.audio = null }
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyRec = any

export class BrowserListener implements Listener {
  private rec: AnyRec = null
  private text = ''
  private resolveStop: ((t: string) => void) | null = null
  static available() { const w = window as AnyRec; return !!(w.SpeechRecognition || w.webkitSpeechRecognition) }
  async start(onPartial: (t: string) => void) {
    const w = window as AnyRec
    const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition
    if (!Ctor) throw new Error('Voice input needs an ElevenLabs key (Settings → Voice) or a browser with speech recognition.')
    this.text = ''
    const rec = new Ctor()
    rec.lang = navigator.language || 'en-US'
    rec.interimResults = true
    rec.continuous = true
    rec.onresult = (e: AnyRec) => {
      let interim = '', fin = ''
      for (let i = 0; i < e.results.length; i++) (e.results[i].isFinal ? (fin += e.results[i][0].transcript) : (interim += e.results[i][0].transcript))
      this.text = fin; onPartial((fin + interim).trim())
    }
    rec.onend = () => { this.resolveStop?.(this.text.trim()); this.resolveStop = null; this.rec = null }
    this.rec = rec
    rec.start()
  }
  stop() { return new Promise<string>(res => { if (!this.rec) return res(this.text.trim()); this.resolveStop = res; this.rec.stop() }) }
  cancel() { this.resolveStop = null; this.rec?.abort?.() }
}

export class BrowserSpeaker implements Speaker {
  private voiceName: string
  private rate: number
  constructor(voiceName = '', rate = 1) { this.voiceName = voiceName; this.rate = rate }
  async speak(text: string, onEnd: () => void) {
    if (!('speechSynthesis' in window)) return onEnd()
    speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text.replace(/```[\s\S]*?```/g, ' ').replace(/[*_#>`]/g, '').slice(0, 3000))
    const v = speechSynthesis.getVoices().find(v => v.name === this.voiceName)
    if (v) u.voice = v
    u.rate = this.rate
    u.onend = onEnd; u.onerror = onEnd
    speechSynthesis.speak(u)
  }
  cancel() { if ('speechSynthesis' in window) speechSynthesis.cancel() }
}

export function makeVoice(useEleven: boolean, browserVoiceName = '', rate = 1): { listener: Listener; speaker: Speaker; provider: string } {
  return useEleven
    ? { listener: new ElevenLabsListener(), speaker: new ElevenLabsSpeaker(), provider: 'ElevenLabs' }
    : { listener: new BrowserListener(), speaker: new BrowserSpeaker(browserVoiceName, rate), provider: 'browser voice' }
}
