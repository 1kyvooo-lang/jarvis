// Call mode: a hands-free, back-and-forth voice conversation.
//
//   listening ──(you start talking)──▶ hearing ──(you pause ~1s)──▶ thinking
//        ▲                                  ▲                           │
//        └────────(reply finished)── speaking ◀──────(reply ready)──────┘
//                                       │
//                         (you talk over him) ─▶ hearing   ← barge-in
//
// Speech start/end is detected locally from the mic level (no audio leaves the Mac
// until you've said something). Each utterance goes to ElevenLabs Scribe, the text
// goes to JARVIS like a typed message, and the answer is spoken back.

export type CallState = 'starting' | 'listening' | 'hearing' | 'thinking' | 'speaking' | 'ended'

export interface CallHooks {
  transcribe(audio: Blob): Promise<string>
  /** Send the user's words; resolve with the reply. May start speaking early (calls onSpeaking). */
  respond(text: string, onSpeaking: () => void): Promise<string>
  /** Speak text; resolve when playback ends (or is stopped). */
  speak(text: string): Promise<void>
  stopSpeaking(): void
  onState(state: CallState): void
  onLevel?(level: number): void
  onError(message: string): void
}

const TICK_MS = 50
const START_MS = 150        // this much continuous voice starts an utterance
const END_SILENCE_MS = 750  // a pause this long ends it
const MIN_SPEECH_MS = 350   // shorter blips (a cough, a click) are ignored
const MAX_UTTERANCE_MS = 30_000
const BARGE_MS = 280        // talking over JARVIS for this long interrupts him
const IDLE_RECYCLE_MS = 12_000
const GAP_MS = 200          // dips shorter than this (between syllables) don't count as silence

const HANG_UP = /^\s*(bye|goodbye|good bye|end (the )?call|hang up|that'?s all|stop listening)[\s.!]*$/i

export class CallSession {
  private hooks: CallHooks
  private stream: MediaStream | null = null
  private ctx: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private buf: Float32Array<ArrayBuffer> | null = null
  private timer: number | null = null
  private recorder: MediaRecorder | null = null
  private chunks: Blob[] = []
  private recStarted = 0
  private state: CallState = 'starting'
  private noise = 0.01
  private calibrating = 0
  private voiceMs = 0
  private quietMs = 0       // gaps between syllables shouldn't reset speech detection
  private silenceMs = 0
  private speechMs = 0
  private uttStart = 0
  private muted = false

  constructor(hooks: CallHooks) { this.hooks = hooks }

  get current() { return this.state }
  private ended() { return this.state === 'ended' }  // read fresh after awaits

  /** Start listening; with `greeting`, JARVIS says it first (e.g. after the wake word). */
  async start(greeting?: string) {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
    } catch (e) {
      const name = (e as { name?: string })?.name
      this.hooks.onError(name === 'NotAllowedError' || name === 'SecurityError'
        ? 'Microphone access is blocked. Allow it for JARVIS, and in System Settings → Privacy & Security → Microphone.'
        : `Microphone error: ${(e as Error)?.message || e}`)
      this.setState('ended')
      return
    }
    this.ctx = new AudioContext()
    const src = this.ctx.createMediaStreamSource(this.stream)
    this.analyser = this.ctx.createAnalyser()
    this.analyser.fftSize = 1024
    src.connect(this.analyser)
    this.buf = new Float32Array(this.analyser.fftSize)
    this.calibrating = 500
    this.timer = window.setInterval(() => this.tick(), TICK_MS)
    if (greeting) {
      this.setState('speaking')
      try { await this.hooks.speak(greeting) } catch { /* still listen */ }
      if (this.state === 'speaking') this.listen()
      return
    }
    this.listen()
  }

  end() {
    if (this.state === 'ended') return
    this.setState('ended')
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    this.hooks.stopSpeaking()
    this.dropRecorder()
    this.stream?.getTracks().forEach(t => t.stop())
    this.ctx?.close().catch(() => {})
    this.stream = null; this.ctx = null; this.analyser = null
  }

  setMuted(m: boolean) {
    this.muted = m
    if (m && (this.state === 'hearing' || this.state === 'listening')) { this.dropRecorder(); this.listen() }
  }

  // ---------------------------------------------------------------- internals

  private setState(s: CallState) { this.state = s; this.hooks.onState(s) }

  private level(): number {
    if (!this.analyser || !this.buf) return 0
    this.analyser.getFloatTimeDomainData(this.buf)
    let sum = 0
    for (let i = 0; i < this.buf.length; i++) sum += this.buf[i] * this.buf[i]
    return Math.sqrt(sum / this.buf.length)
  }

  private get threshold() { return Math.max(0.018, this.noise * 3) }

  private tick() {
    const lvl = this.level()
    this.hooks.onLevel?.(lvl)
    if (this.calibrating > 0) {               // learn the room's background level
      this.noise = this.noise * 0.8 + lvl * 0.2
      this.calibrating -= TICK_MS
      return
    }
    const loud = !this.muted && lvl > this.threshold

    if (this.state === 'listening') {
      if (!loud) this.noise = this.noise * 0.98 + lvl * 0.02
      this.count(loud)
      if (this.voiceMs >= START_MS) {
        this.setState('hearing')
        this.uttStart = Date.now(); this.speechMs = this.voiceMs; this.silenceMs = 0
      } else if (Date.now() - this.recStarted > IDLE_RECYCLE_MS) {
        this.dropRecorder(); this.startRecorder()  // keep idle recordings small
      }
    } else if (this.state === 'hearing') {
      if (loud) { this.speechMs += TICK_MS; this.silenceMs = 0 } else this.silenceMs += TICK_MS
      if (this.silenceMs >= END_SILENCE_MS || Date.now() - this.uttStart > MAX_UTTERANCE_MS) this.finishUtterance()
    } else if (this.state === 'speaking') {
      // Echo cancellation removes most of JARVIS's own voice; require a clearly louder,
      // sustained signal before treating it as you talking over him.
      const barge = !this.muted && lvl > Math.max(this.threshold * 2.5, 0.045)
      this.count(barge)
      if (this.voiceMs >= BARGE_MS) {
        this.hooks.stopSpeaking()
        this.startRecorder()
        this.setState('hearing')
        this.uttStart = Date.now(); this.speechMs = this.voiceMs; this.silenceMs = 0; this.voiceMs = 0; this.quietMs = 0
      }
    }
  }

  /** Accumulate voiced time; only a pause longer than GAP_MS resets it. */
  private count(voiced: boolean) {
    if (voiced) { this.voiceMs += TICK_MS; this.quietMs = 0; return }
    this.quietMs += TICK_MS
    if (this.quietMs >= GAP_MS) this.voiceMs = 0
  }

  private listen() {
    if (this.state === 'ended') return
    this.voiceMs = 0; this.quietMs = 0
    this.startRecorder()
    this.setState('listening')
  }

  private startRecorder() {
    if (!this.stream) return
    this.dropRecorder()
    const mime = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find(m => MediaRecorder.isTypeSupported(m))
    this.chunks = []
    const rec = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined)
    rec.ondataavailable = e => { if (e.data.size) this.chunks.push(e.data) }
    rec.start(250)
    this.recorder = rec
    this.recStarted = Date.now()
  }

  private dropRecorder() {
    const r = this.recorder
    this.recorder = null
    if (r && r.state !== 'inactive') { r.ondataavailable = null; r.onstop = null; r.stop() }
  }

  private stopRecorder(): Promise<Blob | null> {
    const r = this.recorder
    this.recorder = null
    if (!r || r.state === 'inactive') return Promise.resolve(null)
    return new Promise(res => {
      r.onstop = () => res(new Blob(this.chunks, { type: r.mimeType || 'audio/webm' }))
      r.stop()
    })
  }

  private async finishUtterance() {
    const speech = this.speechMs
    this.setState('thinking')
    const blob = await this.stopRecorder()
    if (this.ended()) return
    if (!blob || speech < MIN_SPEECH_MS) { this.listen(); return }
    try {
      const text = (await this.hooks.transcribe(blob)).trim()
      if (this.ended()) return
      if (!text) { this.listen(); return }
      if (HANG_UP.test(text)) { this.end(); return }
      const reply = await this.hooks.respond(text, () => {
        if (this.state === 'thinking') { this.voiceMs = 0; this.quietMs = 0; this.setState('speaking') }
      })
      if (this.ended()) return
      if (this.state !== 'thinking' && this.state !== 'speaking') return   // you talked over him: that reply is dropped
      if (reply.trim()) {
        if (this.state !== 'speaking') { this.voiceMs = 0; this.quietMs = 0; this.setState('speaking') }
        await this.hooks.speak(reply)
      }
    } catch (e) {
      this.hooks.onError((e as Error)?.message || String(e))
    }
    if (this.state === 'speaking' || this.state === 'thinking') this.listen()
  }
}
