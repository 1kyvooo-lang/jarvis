import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { api } from '../api'
import type { Conversation, Message, Status, ToolCall } from '../api'
import { clock, timeAgo, usePoll } from '../hooks'
import { Button, Core, Icon, Pill, inputCls } from '../ui'
import type { CoreState } from '../ui'
import type { CallState } from '../callMode'
import { useJarvis } from '../engine'
import { levels } from '../levels'

export default function Assistant({ status }: { status: Status | null }) {
  const j = useJarvis()
  const { cid, setCid, msgs, busy, voice, partial, notice, call, coreState, label, transcribing } = j
  const [q, setQ] = useState('')
  const convs = usePoll<Conversation[]>(() => api.conversations(q), 0, [q, j.version])
  const [input, setInput] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  const holdRef = useRef<number>(0)
  const [, tick] = useState(0)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [msgs, partial])
  useEffect(() => { if (!call || call === 'ended') return; const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t) }, [call])
  const levelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!call) return
    let raf = 0
    const loop = () => { if (levelRef.current) levelRef.current.style.transform = `scale(${1 + Math.max(levels.mic, levels.out) * 0.6})`; raf = requestAnimationFrame(loop) }
    loop(); return () => cancelAnimationFrame(raf)
  }, [call])

  const send = (text: string) => { if (text.trim()) { setInput(''); j.send(text) } }
  const micDown = () => {
    if (voice === 'listening') { holdRef.current = 0; j.stopListening(); return }
    holdRef.current = Date.now(); j.startListening()
  }
  const micUp = () => { if (holdRef.current && Date.now() - holdRef.current > 400) j.stopListening(); holdRef.current = 0 }
  const micKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (voice === 'listening') j.stopListening(); else j.startListening() }
  }
  void transcribing
  const newChat = () => { j.newChat(); convs.refresh() }

  return (
    <div className="h-full flex min-h-0">
      <aside className="w-[270px] shrink-0 border-r border-seam/70 flex flex-col min-h-0 max-lg:hidden">
        <div className="p-4 space-y-3">
          <Button tone="quiet" className="w-full" onClick={newChat}><Icon name="plus" className="size-4" /> New conversation</Button>
          <input className={inputCls + ' h-9 text-sm'} placeholder="Search conversations" value={q} onChange={e => setQ(e.target.value)} aria-label="Search conversations" />
        </div>
        <ul className="flex-1 overflow-y-auto px-2 pb-4">
          {(convs.data || []).map(c => (
            <li key={c.id} className="group relative">
              <button onClick={() => setCid(c.id)} className={`w-full text-left px-3 py-2.5 rounded-lg ${c.id === cid ? 'bg-plate' : 'hover:bg-graphite'}`}>
                <span className="block truncate text-sm pr-6">{c.title}</span>
                <span className="block text-[12px] text-faint">{timeAgo(c.updated_at)}</span>
              </button>
              <button aria-label={`Delete ${c.title}`} className="absolute right-2 top-3 text-faint hover:text-fault opacity-0 group-hover:opacity-100 focus:opacity-100"
                onClick={async () => { if (confirm('Delete this conversation?')) { await api.deleteConversation(c.id); if (c.id === cid) newChat(); convs.refresh() } }}>
                <Icon name="trash" className="size-4" />
              </button>
            </li>
          ))}
          {convs.data?.length === 0 && <li className="text-faint text-sm px-3">{q ? 'No matches.' : 'Your conversations will appear here.'}</li>}
        </ul>
      </aside>

      <section className="flex-1 min-w-0 flex flex-col min-h-0">
        <div className="flex items-center gap-4 px-8 py-4 border-b border-seam/70">
          <Core state={coreState} size={52} />
          <div className="min-w-0">
            <p className="font-display text-[17px]">{label}</p>
            <p className="text-[13px] text-faint truncate">Hermes{status?.brain.model ? ` · ${status.brain.model}` : ''} · voice: {j.voiceProvider}{j.wake.status === 'listening' ? ' · say “Hey JARVIS”' : ''}{status && !status.agent.online && ' · Mac agent offline'}</p>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-8 py-6" aria-live="polite">
          <div className="max-w-[760px] mx-auto space-y-6">
            {msgs.length === 0 && (
              <div className="pt-16 text-center">
                <Core state={coreState} size={150} />
                <p className="font-display text-xl mt-6">How can I help?</p>
                <div className="flex flex-wrap gap-2 justify-center mt-5">
                  {['What’s my Mac’s battery and disk status?', 'Find files named “invoice” in my Documents', 'Remember that I prefer short answers', 'Open github.com and tell me what’s trending'].map(s => (
                    <Button key={s} size="sm" onClick={() => send(s)} disabled={!status?.brain.ready}>{s}</Button>
                  ))}
                </div>
                {status && !status.brain.ready && <p className="text-amber text-sm mt-6 max-w-[52ch] mx-auto">Hermes isn’t ready: {status.brain.detail || 'starting up…'}</p>}
              </div>
            )}
            {msgs.map(m => <Bubble key={m.id} m={m} />)}
            {partial && <div className="text-right text-dim italic">{partial}…</div>}
            <div ref={endRef} />
          </div>
        </div>

        {call && <CallPanel state={call} busy={busy} seconds={Math.floor((Date.now() - j.callStart) / 1000)} muted={j.muted}
          levelRef={levelRef} coreState={coreState}
          onMute={j.toggleMute} onInterrupt={j.interrupt} onEnd={j.endCall} notice={notice} />}
        <form className={`px-8 pb-6 pt-2 ${call ? 'hidden' : ''}`} onSubmit={e => { e.preventDefault(); send(input) }}>
          <div className="max-w-[760px] mx-auto">
            {notice && <p className="text-amber text-sm mb-2" role="alert">{notice}</p>}
            <div className="panel flex items-end gap-2 p-2 focus-within:border-arc/60">
              <textarea value={input} onChange={e => setInput(e.target.value)} rows={1}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
                placeholder={voice === 'listening' ? 'Listening…' : 'Message JARVIS'} aria-label="Message"
                className="flex-1 resize-none bg-transparent outline-none px-2 py-2 max-h-40 placeholder:text-faint" />
              <button type="button" aria-label={voice === 'listening' ? 'Stop listening' : 'Push to talk'} aria-pressed={voice === 'listening'}
                onPointerDown={micDown} onPointerUp={micUp} onKeyDown={micKey}
                className={`size-10 grid place-items-center rounded-lg border ${voice === 'listening' ? 'border-arc text-arc bg-arc/10 shadow-[0_0_20px_-4px_#3CE7FF]' : 'border-seam text-dim hover:text-ink'}`}>
                <Icon name="mic" />
              </button>
              <button type="button" onClick={() => j.startCall()} aria-label="Start a voice call" title="Talk hands-free, like a phone call"
                className="h-10 px-3 inline-flex items-center gap-2 rounded-lg border border-seam text-dim hover:text-ink hover:border-arc/60 text-sm">
                <Icon name="phone" /><span className="max-sm:hidden">Call</span>
              </button>
              {busy || voice === 'speaking'
                ? <button type="button" onClick={j.stop} aria-label="Stop" className="size-10 grid place-items-center rounded-lg bg-fault/15 text-fault border border-fault/50"><Icon name="stop" /></button>
                : <button aria-label="Send" disabled={!input.trim() || !status?.brain.ready} className="size-10 grid place-items-center rounded-lg bg-arc text-black disabled:opacity-30"><Icon name="send" /></button>}
            </div>
            <p className="text-[12px] text-faint mt-2">Enter to send · Shift+Enter for a new line · tap the mic to talk and tap again to send, or hold it while you speak</p>
          </div>
        </form>
      </section>
    </div>
  )
}

function Bubble({ m }: { m: Message }) {
  if (m.role === 'event') {
    return <p className="text-[13px] text-amber/90 border-l-2 border-amber/50 pl-3">{m.text}</p>
  }
  if (m.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] bg-plate border border-seam rounded-2xl rounded-br-md px-4 py-2.5">
          <p className="whitespace-pre-wrap">{m.text}</p>
          <p className="text-[11px] text-faint mt-1 text-right">{clock(m.created_at)}</p>
        </div>
      </div>
    )
  }
  const parts = m.parts?.length ? m.parts : [
    ...(m.tools || []).map(t => ({ type: 'tool' as const, id: t.id })), ...(m.text ? [{ type: 'text' as const, text: m.text }] : [])]
  const running = (m.tools || []).some(t => t.status === 'running')
  return (
    <div className="flex gap-3">
      <span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-arc shadow-[0_0_12px_#3CE7FF]" aria-hidden />
      <div className="flex-1 min-w-0 space-y-2">
        {parts.map((p, i) => p.type === 'text'
          ? <div key={i} className={`prose-j ${m.streaming && !running && i === parts.length - 1 ? 'caret' : ''}`}><Markdown>{p.text}</Markdown></div>
          : (() => { const t = (m.tools || []).find(x => x.id === p.id); return t ? <ToolLine key={i} t={t} /> : null })())}
        {!parts.length && m.streaming && <p className="text-dim caret">Thinking</p>}
        {m.error && <p className={`text-sm ${m.error === 'Stopped.' ? 'text-faint' : 'text-fault'}`} role="alert">{m.error}</p>}
        <p className="text-[11px] text-faint">{clock(m.created_at)}</p>
      </div>
    </div>
  )
}

function ToolLine({ t }: { t: ToolCall }) {
  const [open, setOpen] = useState(false)
  const st = t.status ?? (t.is_error ? 'error' : t.result?.startsWith('Approval #') ? 'pending_approval' : 'ok')
  const tone = st === 'ok' ? 'ok' : st === 'running' ? 'arc' : st === 'pending_approval' ? 'amber' : 'fault'
  const text = { ok: 'done', running: 'running', pending_approval: 'awaiting your approval', error: 'failed' }[st] ?? st
  const detail = t.output !== undefined ? JSON.stringify(t.output, null, 2) : t.error ?? t.result
  return (
    <div className="text-sm">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-2 text-dim hover:text-ink" aria-expanded={open}>
        <span className="font-display text-ink">{t.name}</span>
        <span className="text-faint truncate max-w-[340px]">{Object.keys(t.input || {}).length ? JSON.stringify(t.input) : ''}</span>
        <Pill tone={tone}>{text}</Pill>
      </button>
      {open && detail && <pre className="mt-1.5 text-[12px] bg-black border border-seam rounded-lg p-3 max-h-60 overflow-auto text-dim whitespace-pre-wrap">{detail}</pre>}
    </div>
  )
}

function CallPanel({ state, busy, seconds, muted, levelRef, coreState, onMute, onInterrupt, onEnd, notice }: {
  state: CallState; busy: boolean; seconds: number; muted: boolean; levelRef: React.RefObject<HTMLDivElement | null>
  coreState: CoreState; onMute: () => void; onInterrupt: () => void; onEnd: () => void; notice: string | null
}) {
  const label = muted ? 'Muted' : {
    starting: 'Connecting…', listening: 'Listening — go ahead', hearing: 'Hearing you…',
    thinking: busy ? 'Working on it…' : 'Thinking…', speaking: 'JARVIS is speaking — talk to interrupt', ended: 'Call ended',
  }[state]
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0'), ss = String(seconds % 60).padStart(2, '0')
  return (
    <div className="px-8 pb-6 pt-2">
      <div className="max-w-[760px] mx-auto panel p-5 flex flex-wrap items-center gap-5 border-arc/40">
        <div className="relative size-[72px] grid place-items-center">
          <div ref={levelRef} className="absolute inset-2 rounded-full bg-arc/15 transition-transform duration-75" aria-hidden />
          <Core state={coreState} size={72} />
        </div>
        <div className="flex-1 min-w-[180px]">
          <p className="font-display text-lg" aria-live="polite">{label}</p>
          <p className="text-[13px] text-faint tabular-nums">On call · {mm}:{ss} · say “goodbye” to hang up</p>
          {notice && <p className="text-amber text-[13px] mt-1" role="alert">{notice}</p>}
        </div>
        <div className="flex gap-2">
          {state === 'speaking' && <Button size="sm" onClick={onInterrupt}>Interrupt</Button>}
          <Button size="sm" onClick={onMute} aria-pressed={muted}>{muted ? 'Unmute' : 'Mute'}</Button>
          <Button size="sm" tone="danger" onClick={onEnd}><Icon name="phone" className="size-4 rotate-[135deg]" />End call</Button>
        </div>
      </div>
    </div>
  )
}
