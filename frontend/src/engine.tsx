// The one JARVIS conversation engine shared by every screen: typed chat, push-to-talk,
// hands-free calls and the "Hey JARVIS" wake word. The Command Center and the Assistant
// page are just two views of it, so the animated core always reflects what he's doing.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api, streamChat, transcribe } from './api'
import type { ChatEvent, Message, Settings, Status } from './api'
import { CallSession } from './callMode'
import type { CallState } from './callMode'
import { levels } from './levels'
import type { CoreState } from './ui'
import { makeVoice } from './voice'
import { WakeListener } from './wake'
import type { WakeStatus } from './wake'

type VoiceState = 'idle' | 'listening' | 'speaking'

export interface Engine {
  status: Status | null
  settings: Settings | null
  reloadSettings: () => void
  cid: string | null
  setCid: (c: string | null) => void
  msgs: Message[]
  busy: boolean
  partial: string
  notice: string | null
  setNotice: (n: string | null) => void
  voice: VoiceState
  transcribing: boolean
  call: CallState | null
  callStart: number
  muted: boolean
  coreState: CoreState
  label: string
  voiceProvider: string
  version: number
  heard: string
  reply: string
  wake: { status: WakeStatus; detail?: string }
  send: (text: string, opts?: { silent?: boolean; voice?: boolean }) => Promise<string>
  stop: () => void
  newChat: () => void
  startCall: (greeting?: string) => Promise<void>
  endCall: () => void
  toggleMute: () => void
  interrupt: () => void
  startListening: () => Promise<void>
  stopListening: () => Promise<void>
}

const Ctx = createContext<Engine | null>(null)
export const useJarvis = () => {
  const e = useContext(Ctx)
  if (!e) throw new Error('useJarvis outside JarvisProvider')
  return e
}

export function JarvisProvider({ status, onWake, children }: { status: Status | null; onWake: () => void; children: ReactNode }) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const reloadSettings = useCallback(() => { api.settings().then(r => setSettings(r.settings)).catch(() => {}) }, [])
  useEffect(() => {
    reloadSettings()
    addEventListener('jarvis:settings', reloadSettings)
    return () => removeEventListener('jarvis:settings', reloadSettings)
  }, [reloadSettings])

  const [cid, setCidState] = useState<string | null>(() => { try { return sessionStorage.getItem('jarvis.cid') } catch { return null } })
  const cidRef = useRef<string | null>(cid)
  const setCid = useCallback((c: string | null) => {
    cidRef.current = c; setCidState(c)
    try { if (c) sessionStorage.setItem('jarvis.cid', c); else sessionStorage.removeItem('jarvis.cid') } catch { /* ignore */ }
  }, [])
  const [msgs, setMsgs] = useState<Message[]>([])
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [voice, setVoice] = useState<VoiceState>('idle')
  const [partial, setPartial] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [version, setVersion] = useState(0)
  const [heard, setHeard] = useState('')
  const [reply, setReply] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const lastWasVoice = useRef(false)

  useEffect(() => {
    if (!cid) { setMsgs([]); return }
    if (busyRef.current) return
    api.conversation(cid).then(c => setMsgs(c.messages)).catch(() => setCid(null))
  }, [cid, setCid])
  // Pick up approval outcomes that land in the open conversation.
  useEffect(() => {
    if (!cid || busy) return
    const t = setInterval(() => api.conversation(cid).then(c => setMsgs(p => (c.messages.length !== p.length ? c.messages : p))).catch(() => {}), 4000)
    return () => clearInterval(t)
  }, [cid, busy])

  const useEleven = !!status?.voice.elevenlabs && settings?.voice.provider !== 'browser'
  const voiceKit = useMemo(() => makeVoice(useEleven, settings?.voice.browser_voice_name, settings?.voice.rate),
    [useEleven, settings?.voice.browser_voice_name, settings?.voice.rate])

  const updateLast = (fn: (m: Message) => Message) =>
    setMsgs(prev => { if (!prev.length) return prev; const c = prev.slice(); c[c.length - 1] = fn(c[c.length - 1]); return c })

  const speak = useCallback((text: string) => {
    if (!text.trim() || !(settings?.voice.auto_speak || lastWasVoice.current)) return
    setVoice('speaking')
    voiceKit.speaker.speak(text, () => setVoice('idle')).catch(e => { setVoice('idle'); setNotice(`Couldn't speak the reply: ${(e as Error).message}`) })
  }, [settings, voiceKit])

  const send = useCallback(async (text: string, opts: { silent?: boolean; voice?: boolean } = {}): Promise<string> => {
    text = text.trim()
    if (!text || busyRef.current) return ''
    lastWasVoice.current = !!opts.voice
    busyRef.current = true
    voiceKit.speaker.cancel()
    setNotice(null); setBusy(true); setHeard(text); setReply('')
    const now = new Date().toISOString()
    setMsgs(prev => [...prev, { id: `u${Date.now()}`, role: 'user', text, created_at: now },
      { id: `a${Date.now()}`, role: 'assistant', text: '', tools: [], created_at: now, streaming: true }])
    const ac = new AbortController(); abortRef.current = ac
    let full = ''
    try {
      await streamChat(cidRef.current, text, (e: ChatEvent) => {
        if (e.type === 'conversation') { if (e.id !== cidRef.current) setCid(e.id) }
        else if (e.type === 'text') {
          full += e.delta
          setReply(full)
          updateLast(m => {
            const parts = [...(m.parts || [])]
            const last = parts[parts.length - 1]
            if (last?.type === 'text') parts[parts.length - 1] = { type: 'text', text: last.text + e.delta }
            else parts.push({ type: 'text', text: e.delta })
            return { ...m, text: m.text + e.delta, parts }
          })
        } else if (e.type === 'tool_start') {
          full = ''  // only the answer after the last tool is spoken
          updateLast(m => ({ ...m, parts: [...(m.parts || []), { type: 'tool', id: e.id }], tools: [...(m.tools || []), { id: e.id, name: e.name, input: e.input, status: 'running' }] }))
        } else if (e.type === 'tool_result') {
          updateLast(m => ({ ...m, tools: (m.tools || []).map(t => t.id === e.id ? { ...t, status: e.status, output: e.output, error: e.error, approval_id: e.approval_id } : t) }))
        } else if (e.type === 'error') updateLast(m => ({ ...m, error: e.message }))
        else if (e.type === 'stopped') updateLast(m => ({ ...m, error: 'Stopped.' }))
      }, ac.signal)
      if (!opts.silent) speak(full)
      return full
    } catch (err) {
      updateLast(m => ({ ...m, error: (err as Error).name === 'AbortError' ? 'Stopped.' : (err as Error).message }))
    } finally {
      updateLast(m => ({ ...m, streaming: false }))
      setBusy(false); busyRef.current = false; abortRef.current = null
      setVersion(v => v + 1)
    }
    return ''
  }, [speak, voiceKit, setCid])

  const stop = useCallback(() => {
    if (cidRef.current) api.stopChat(cidRef.current).catch(() => {})
    abortRef.current?.abort()
    voiceKit.speaker.cancel(); voiceKit.listener.cancel(); setVoice('idle'); setPartial('')
  }, [voiceKit])

  // ---- hands-free call
  const [call, setCall] = useState<CallState | null>(null)
  const [callStart, setCallStart] = useState(0)
  const [muted, setMuted] = useState(false)
  const callRef = useRef<CallSession | null>(null)

  const startCall = useCallback(async (greeting?: string) => {
    if (callRef.current) return
    if (!useEleven) { setNotice('Hands-free talk needs ElevenLabs. Add your key in Settings → Voice.'); return }
    if (!status?.brain.ready) { setNotice('Hermes isn’t ready yet.'); return }
    voiceKit.speaker.cancel(); setNotice(null); setMuted(false)
    const session = new CallSession({
      transcribe: blob => transcribe(blob),
      respond: text => send(text, { silent: true, voice: true }),
      speak: text => new Promise<void>(resolve => {
        voiceKit.speaker.speak(text, resolve).catch(e => {
          if ((e as Error).name !== 'AbortError') setNotice(`Couldn't speak: ${(e as Error).message}`)
          resolve()
        })
      }),
      stopSpeaking: () => voiceKit.speaker.cancel(),
      onState: st => { setCall(st); if (st === 'ended') { callRef.current = null; levels.mic = 0; setTimeout(() => setCall(c => (c === 'ended' ? null : c)), 600) } },
      onLevel: lvl => { levels.mic = Math.min(1, lvl * 9) },
      onError: msg => setNotice(msg),
    })
    callRef.current = session
    setCallStart(Date.now()); setCall('starting')
    await session.start(greeting)
  }, [useEleven, status?.brain.ready, voiceKit, send])
  const endCall = useCallback(() => {
    callRef.current?.end()
    if (cidRef.current && busyRef.current) api.stopChat(cidRef.current).catch(() => {})
  }, [])
  const toggleMute = useCallback(() => { setMuted(m => { callRef.current?.setMuted(!m); return !m }) }, [])
  const interrupt = useCallback(() => voiceKit.speaker.cancel(), [voiceKit])
  useEffect(() => () => { callRef.current?.end() }, [])

  // ---- push-to-talk
  const [transcribing, setTranscribing] = useState(false)
  const startListening = useCallback(async () => {
    voiceKit.speaker.cancel(); setPartial(''); setNotice(null)
    try { await voiceKit.listener.start(t => setPartial(t)); setVoice('listening') }
    catch (e) { setNotice((e as Error).message); setVoice('idle') }
  }, [voiceKit])
  const stopListening = useCallback(async () => {
    setVoice('idle'); setTranscribing(useEleven); if (useEleven) setPartial('Transcribing…')
    try {
      const text = await voiceKit.listener.stop()
      setPartial('')
      if (text) send(text, { voice: true })
      else setNotice('I didn’t catch that — try again.')
    } catch (e) { setPartial(''); setNotice((e as Error).message) }
    finally { setTranscribing(false) }
  }, [voiceKit, useEleven, send])

  // ---- "Hey JARVIS"
  const [wakeState, setWakeState] = useState<{ status: WakeStatus; detail?: string }>({ status: 'off' })
  const wakeRef = useRef<WakeListener | null>(null)
  const onWakeRef = useRef(onWake); onWakeRef.current = onWake
  const startCallRef = useRef(startCall); startCallRef.current = startCall
  const wakeOn = !!settings?.wake?.enabled && useEleven && !!status?.brain.ready
  useEffect(() => {
    if (!wakeOn) { wakeRef.current?.stop(); wakeRef.current = null; return }
    const w = new WakeListener(() => {
      if (callRef.current) return
      onWakeRef.current()
      startCallRef.current(settings?.wake?.greeting || 'Yes? What do you need?')
    }, (s, detail) => setWakeState({ status: s, detail }))
    wakeRef.current = w
    w.start()
    return () => { w.stop(); if (wakeRef.current === w) wakeRef.current = null }
  }, [wakeOn, settings?.wake?.greeting])
  // Don't listen for the wake word while he's already talking with you.
  useEffect(() => { wakeRef.current?.setPaused(!!call || voice !== 'idle' || busy) }, [call, voice, busy])

  const newChat = useCallback(() => { stop(); setCid(null); setMsgs([]); setHeard(''); setReply('') }, [stop, setCid])

  const coreState: CoreState = status?.emergency_stop ? 'stopped' : !status?.brain.ready ? 'offline'
    : call === 'speaking' ? 'speaking' : call === 'listening' || call === 'hearing' ? 'listening'
    : call === 'thinking' && !busy ? 'thinking' : transcribing ? 'thinking'
    : voice === 'listening' ? 'listening' : voice === 'speaking' ? 'speaking'
    : busy && msgs[msgs.length - 1]?.tools?.some(t => t.status === 'running') ? 'acting' : busy ? 'thinking' : 'idle'
  const label = { idle: 'Ready', listening: 'Listening…', thinking: 'Thinking…', speaking: 'Speaking…', acting: 'Working on your Mac…', stopped: 'Actions halted', offline: 'Offline' }[coreState]

  const value: Engine = {
    status, settings, reloadSettings, cid, setCid, msgs, busy, partial, notice, setNotice, voice, transcribing,
    call, callStart, muted, coreState, label, voiceProvider: voiceKit.provider, version, heard, reply,
    wake: wakeState, send, stop, newChat, startCall, endCall, toggleMute, interrupt, startListening, stopListening,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
