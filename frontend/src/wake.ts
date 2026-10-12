// "Hey JARVIS": streams the microphone (16 kHz mono) to the local JARVIS backend, where
// openWakeWord listens for the phrase. Audio stays on this Mac and is never recorded.

const WORKLET = `
class Tap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(2560); this.n = 0 }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch) for (let i = 0; i < ch.length; i++) {
      this.buf[this.n++] = ch[i]
      if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0 }
    }
    return true
  }
}
registerProcessor('jarvis-tap', Tap)`

export type WakeStatus = 'off' | 'starting' | 'listening' | 'paused' | 'error'

export class WakeListener {
  private ws: WebSocket | null = null
  private ctx: AudioContext | null = null
  private stream: MediaStream | null = null
  private paused = false
  private stopped = true
  private retry: number | null = null
  private onWake: () => void
  private onStatus: (s: WakeStatus, detail?: string) => void

  constructor(onWake: () => void, onStatus: (s: WakeStatus, detail?: string) => void) {
    this.onWake = onWake; this.onStatus = onStatus
  }

  async start() {
    if (!this.stopped) return
    this.stopped = false
    this.onStatus('starting')
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      })
      this.ctx = new AudioContext({ sampleRate: 16000 })
      const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
      await this.ctx.audioWorklet.addModule(url)
      const src = this.ctx.createMediaStreamSource(this.stream)
      const node = new AudioWorkletNode(this.ctx, 'jarvis-tap')
      node.port.onmessage = e => this.send(e.data as Float32Array)
      src.connect(node)   // not connected to the speakers
    } catch (e) {
      const name = (e as { name?: string })?.name
      this.onStatus('error', name === 'NotAllowedError' ? 'Microphone access is blocked for JARVIS.' : `Microphone error: ${(e as Error).message}`)
      this.stop()
      return
    }
    this.connect()
  }

  stop() {
    this.stopped = true
    if (this.retry) clearTimeout(this.retry)
    this.ws?.close(); this.ws = null
    this.stream?.getTracks().forEach(t => t.stop()); this.stream = null
    this.ctx?.close().catch(() => {}); this.ctx = null
    this.onStatus('off')
  }

  /** Pause while a conversation is running (his own voice must not wake him). */
  setPaused(p: boolean) {
    if (p === this.paused) return
    this.paused = p
    if (!p && this.ws?.readyState === WebSocket.OPEN) this.ws.send('reset')
    if (!this.stopped) this.onStatus(p ? 'paused' : 'listening')
  }

  private connect() {
    if (this.stopped) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/api/wake/ws`)
    ws.binaryType = 'arraybuffer'
    ws.onmessage = e => {
      const m = JSON.parse(e.data)
      if (m.type === 'ready') this.onStatus(this.paused ? 'paused' : 'listening')
      else if (m.type === 'wake' && !this.paused) this.onWake()
      else if (m.type === 'error') { this.onStatus('error', m.message); this.stopped = true }
    }
    ws.onclose = () => {
      if (this.ws === ws) this.ws = null
      if (!this.stopped) this.retry = window.setTimeout(() => this.connect(), 3000)   // backend restarting
    }
    this.ws = ws
  }

  private send(f: Float32Array) {
    if (this.paused || this.ws?.readyState !== WebSocket.OPEN) return
    const pcm = new Int16Array(f.length)
    for (let i = 0; i < f.length; i++) pcm[i] = Math.max(-1, Math.min(1, f[i])) * 0x7fff
    this.ws.send(pcm.buffer)
  }
}
