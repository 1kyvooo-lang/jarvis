// Command Center: the home screen. Everything shown is live data from this Mac.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import type { ReactNode } from 'react'
import { api } from '../api'
import type { Activity, Memory, Reminder, Task } from '../api'
import type { PageId } from '../App'
import { useJarvis } from '../engine'
import { timeAgo, usePoll } from '../hooks'
import HoloCore, { Wave } from '../components/HoloCore'
import { Icon } from '../ui'
import CountUp from '../components/reactbits/CountUp'
import DecryptedText from '../components/reactbits/DecryptedText'
import ShinyText from '../components/reactbits/ShinyText'
import SpotlightCard from '../components/reactbits/SpotlightCard'

type Sys = Awaited<ReturnType<typeof api.system>>

function Panel({ title, right, children, className = '' }: { title: string; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`hud p-4 min-w-0 ${className}`}>
      <header className="flex items-center justify-between mb-3">
        <h2 className="hud-title">{title}</h2>
        {right}
      </header>
      {children}
    </section>
  )
}

function Ring({ label, value }: { label: string; value: number | null }) {
  const v = Math.max(0, Math.min(100, value ?? 0))
  const r = 30, C = 2 * Math.PI * r
  const tone = v > 85 ? '#FF5A6A' : v > 65 ? '#FFB547' : '#3CE7FF'
  return (
    <div className="flex flex-col items-center gap-1">
      <svg viewBox="0 0 80 80" className="size-[84px]" role="img" aria-label={`${label} ${value == null ? 'unknown' : `${Math.round(v)}%`}`}>
        <circle cx="40" cy="40" r={r} fill="none" stroke="#1b2a36" strokeWidth="6" />
        <circle cx="40" cy="40" r={r} fill="none" stroke={tone} strokeWidth="6" strokeLinecap="round"
          strokeDasharray={`${(v / 100) * C} ${C}`} transform="rotate(-90 40 40)" style={{ transition: 'stroke-dasharray .8s ease', filter: `drop-shadow(0 0 6px ${tone})` }} />
        <text x="40" y="37" textAnchor="middle" className="fill-dim" fontSize="9">{label}</text>
        <text x="40" y="51" textAnchor="middle" className="fill-ink font-display" fontSize="14">{value == null ? '—' : `${Math.round(v)}%`}</text>
      </svg>
    </div>
  )
}

function Row({ icon, name, value, tone = 'ok' }: { icon: string; name: string; value: string; tone?: 'ok' | 'warn' | 'bad' | 'off' }) {
  const c = { ok: 'text-ok', warn: 'text-amber', bad: 'text-fault', off: 'text-faint' }[tone]
  return (
    <li className="hud-row flex items-center gap-3 px-3 py-2">
      <span className="size-8 grid place-items-center rounded-md bg-arc/10 text-arc border border-arc/25"><Icon name={icon} className="size-4" /></span>
      <span className="min-w-0">
        <span className="block text-[13px] text-ink leading-tight">{name}</span>
        <span className={`block text-[12px] leading-tight truncate ${c}`}>{value}</span>
      </span>
    </li>
  )
}

function SystemCard({ name, state, detail, active }: { name: string; state: string; detail: string; active: boolean }) {
  return (
    <div className="hud-row p-3 flex items-center gap-3 min-w-0">
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-ink">{name}</p>
        <p className={`text-[12px] ${active ? 'text-ok' : state === 'Offline' ? 'text-fault' : 'text-dim'}`}>● {state}</p>
        <p className="text-[11px] text-faint truncate">{detail}</p>
      </div>
      <Wave active={active} bars={12} className="h-6 opacity-80" />
    </div>
  )
}

function feedTag(a: Activity): { tag: string; cls: string } {
  if (a.status === 'error') return { tag: 'ERROR', cls: 'text-fault border-fault/40' }
  if (a.status === 'pending') return { tag: 'APPROVAL', cls: 'text-amber border-amber/40' }
  if (a.status === 'denied') return { tag: 'DENIED', cls: 'text-fault border-fault/40' }
  if (a.source === 'user') return { tag: 'YOU', cls: 'text-arc border-arc/40' }
  return { tag: 'INFO', cls: 'text-dim border-seam' }
}

export default function CommandCenter({ go }: { go: (p: PageId) => void }) {
  const j = useJarvis()
  const s = j.status
  const [now, setNow] = useState(new Date())
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t) }, [])
  const sys = usePoll<Sys>(api.system, 3000)
  const feed = usePoll<Activity[]>(() => api.activity(7), 5000)
  const tasks = usePoll<Task[]>(api.tasks, 8000)
  const mems = usePoll<Memory[]>(() => api.memories(''), 30000)
  const rems = usePoll<Reminder[]>(api.reminders, 15000)

  const root = useRef<HTMLDivElement>(null)
  const coreBox = useRef<HTMLElement>(null)
  useLayoutEffect(() => {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const ctx = gsap.context(() => {
      gsap.from('.hud', { y: 18, opacity: 0, duration: 0.7, ease: 'power3.out', stagger: 0.06 })
      gsap.from('.core-title', { scale: 0.85, opacity: 0, duration: 1.1, ease: 'expo.out', delay: 0.2 })
    }, root)
    return () => ctx.revert()
  }, [])
  useEffect(() => {
    const el = coreBox.current
    if (!el || matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const glow = j.coreState === 'listening' || j.coreState === 'speaking'
    gsap.to(el, { boxShadow: glow ? '0 0 60px -10px rgba(60,231,255,.65), inset 0 0 60px rgba(60,231,255,.12)' : '0 0 0 0 rgba(0,0,0,0), inset 0 0 30px rgba(60,231,255,.04)', duration: 0.6, ease: 'power2.out' })
    if (j.coreState === 'listening' && j.call === 'listening') gsap.fromTo(el.querySelector('.core-title'), { scale: 1.08 }, { scale: 1, duration: 0.8, ease: 'elastic.out(1, 0.5)' })
  }, [j.coreState, j.call])

  const [fixing, setFixing] = useState(false)
  const healthy = !!s && s.brain.ready && s.agent.online && !s.emergency_stop
  const degraded = !!s && !healthy
  const inCall = !!j.call && j.call !== 'ended'
  const talkLabel = !inCall ? (j.wake.status === 'listening' ? 'Say “Hey JARVIS” or tap' : 'Tap to talk')
    : j.call === 'speaking' ? 'Speaking…' : j.call === 'thinking' ? 'Thinking…' : j.call === 'hearing' ? 'Hearing you…' : 'I am listening…'

  type Item = { key: string; when: string | null; title: string; status: string; dot: string; onCancel?: () => void }
  const timeline: Item[] = [
    ...(rems.data || []).map(r => ({ key: `r${r.id}`, when: r.due_at, title: `⏰ ${r.text}`, status: r.via, dot: 'bg-amber',
      onCancel: () => api.cancelReminder(r.id).then(() => rems.refresh()) })),
    ...(tasks.data || []).filter(t => ['todo', 'queued', 'running', 'proposed'].includes(t.status))
      .map(t => ({ key: `t${t.id}`, when: t.due_at, title: t.title, status: t.status,
        dot: t.status === 'running' ? 'bg-arc' : t.status === 'proposed' ? 'bg-amber' : 'bg-ok' })),
  ].sort((a, b) => (a.when ? new Date(a.when).getTime() : 9e15) - (b.when ? new Date(b.when).getTime() : 9e15)).slice(0, 6)
  const briefing = () => j.send('Give me a short executive briefing: my open tasks, anything waiting for my approval, and my Mac’s status. Keep it brief.', { voice: true })

  return (
    <div ref={root} className="hud-field min-h-full px-6 py-5 flex flex-col gap-4">
      {/* top bar */}
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 max-md:grid-cols-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="hud-chip">SYSTEM STATUS <b className={healthy ? 'text-ok' : 'text-amber'}>● {healthy ? 'OPTIMAL' : s?.emergency_stop ? 'HALTED' : degraded ? 'DEGRADED' : '…'}</b></span>
          {j.wake.status === 'listening' && <span className="hud-chip text-arc">WAKE WORD · “HEY JARVIS”</span>}
          {j.wake.status === 'error' && <span className="hud-chip text-amber" title={j.wake.detail}>WAKE WORD OFF</span>}
        </div>
        <div className="text-center">
          <p className="text-[12px] text-dim">{now.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</p>
          <p className="font-display text-[34px] leading-none tracking-wider text-ink tabular-nums drop-shadow-[0_0_14px_rgba(60,231,255,.45)]">
            {now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </p>
        </div>
        <div className="flex justify-end gap-2">
          {!!s?.counts.pending_approvals && <button className="hud-chip text-amber" onClick={() => go('activity')}>{s.counts.pending_approvals} WAITING FOR YOU</button>}
          {s?.update?.available && <button className="hud-chip text-arc" onClick={() => go('settings')}>UPDATE READY</button>}
        </div>
      </div>

      {/* row 1 */}
      <div className="grid grid-cols-12 gap-4">
        <Panel title="AI Core Overview" className="col-span-3 max-xl:col-span-6 max-md:col-span-12">
          <ul className="space-y-2">
            <Row icon="overview" name="AI Core (Hermes)" value={s?.brain.ready ? (s.brain.model || 'Active') : 'Offline'} tone={s?.brain.ready ? 'ok' : 'bad'} />
            <Row icon="memory" name="Memory" value={`${s?.counts.memories ?? 0} stored`} />
            <Row icon="mic" name="Voice" value={s?.voice.elevenlabs ? 'ElevenLabs online' : 'Basic voice'} tone={s?.voice.elevenlabs ? 'ok' : 'warn'} />
            <Row icon="computer" name="Mac agent" value={s?.agent.online ? `${s.agent.tool_count ?? 0} tools` : 'Offline'} tone={s?.agent.online ? (s.agent.stopped ? 'warn' : 'ok') : 'bad'} />
            <Row icon="phone" name="Phone line" value={s?.phone.configured ? (s.phone.public_url ? 'Online' : 'Connecting') : 'Not set up'} tone={s?.phone.configured ? 'ok' : 'off'} />
            <Row icon="settings" name="System" value={healthy ? 'Optimal' : 'Needs attention'} tone={healthy ? 'ok' : 'warn'} />
          </ul>
          {degraded && !s?.emergency_stop && (
            <button disabled={fixing} onClick={async () => { setFixing(true); try { await api.restartServices() } finally { setTimeout(() => setFixing(false), 8000) } }}
              className="hud-row w-full mt-3 px-3 py-2 text-[13px] text-amber hover:text-white disabled:opacity-60">
              {fixing ? 'Restarting Hermes and the Mac agent…' : '↻ Restart Hermes & Mac agent'}
            </button>
          )}
          {s && !s.brain.ready && s.brain.detail && <p className="text-[12px] text-faint mt-2 whitespace-pre-wrap line-clamp-4" title={s.brain.detail}>Hermes: {s.brain.detail}</p>}
          {s && !s.agent.online && (s.agent.service?.detail || s.agent.error) && <p className="text-[12px] text-faint mt-2 whitespace-pre-wrap line-clamp-6" title={s.agent.service?.detail || s.agent.error}>Mac agent: {s.agent.service?.detail || s.agent.error}</p>}
        </Panel>

        <section ref={coreBox} className="col-span-6 max-xl:col-span-12 order-first xl:order-none hud relative min-h-[360px] overflow-hidden">
          <HoloCore state={j.coreState} className="absolute inset-0" />
          <div className="absolute inset-0 grid place-items-center pointer-events-none">
            <div className="text-center core-title">
              <p className="font-display text-[44px] tracking-[0.35em] text-white drop-shadow-[0_0_18px_rgba(60,231,255,.9)] pl-[0.35em]">
                <DecryptedText text="JARVIS" animateOn="view" sequential speed={70} characters="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" encryptedClassName="text-arc/70" />
              </p>
              <p className="font-display text-[13px] tracking-[0.5em] text-arc/90 pl-[0.5em]">AI CORE</p>
              <p className="text-[12px] text-dim mt-1">{j.label}</p>
            </div>
          </div>
          {(j.heard || j.reply) && (
            <div className="absolute bottom-3 inset-x-4 text-center pointer-events-none">
              {j.heard && <p className="text-[13px] text-dim truncate">“{j.heard}”</p>}
              {j.reply && <p className="text-[14px] text-ink line-clamp-2">{j.reply}</p>}
            </div>
          )}
        </section>

        <Panel title="Live Intelligence Feed" className="col-span-3 max-xl:col-span-6 max-md:col-span-12"
          right={<span className="text-[11px] text-ok">● LIVE</span>}>
          <ul className="space-y-2">
            {(feed.data || []).map(a => {
              const t = feedTag(a)
              return (
                <li key={a.id} className="hud-row px-3 py-2 flex items-start gap-2">
                  <span className="flex-1 min-w-0">
                    <span className="block text-[13px] text-ink truncate">{a.action}</span>
                    <span className="block text-[11px] text-faint">{timeAgo(a.ts)}{a.tool ? ` · ${a.tool}` : ''}</span>
                  </span>
                  <span className={`text-[10px] border rounded px-1.5 py-0.5 ${t.cls}`}>{t.tag}</span>
                </li>
              )
            })}
            {feed.data?.length === 0 && <li className="text-faint text-sm">Nothing yet. Activity appears here live.</li>}
          </ul>
          <button className="text-[12px] text-arc mt-3 hover:underline" onClick={() => go('activity')}>View full log ›</button>
        </Panel>
      </div>

      {/* row 2 */}
      <div className="grid grid-cols-12 gap-4">
        <Panel title="Active Systems" className="col-span-5 max-xl:col-span-12">
          <div className="grid grid-cols-2 max-sm:grid-cols-1 gap-2">
            <SystemCard name="Brain · Hermes" state={!s?.brain.ready ? 'Offline' : j.busy ? 'Active' : 'Standby'} detail={s?.brain.model || '—'} active={j.busy} />
            <SystemCard name="Voice" state={inCall ? 'In conversation' : j.wake.status === 'listening' ? 'Listening for wake word' : 'Standby'} detail={j.voiceProvider} active={inCall || j.voice !== 'idle'} />
            <SystemCard name="Browser · Playwright" state={s?.browser.available ? (j.coreState === 'acting' ? 'Active' : 'Standby') : 'Not installed'} detail="Own Chrome window" active={j.coreState === 'acting'} />
            <SystemCard name="Mac agent" state={s?.agent.online ? (s.agent.stopped ? 'Halted' : 'Standby') : 'Offline'} detail={`${s?.agent.executed ?? 0} actions run`} active={false} />
            <SystemCard name="Phone line" state={s?.phone.configured ? 'Online' : 'Not set up'} detail={s?.phone.configured ? 'Twilio' : 'Settings → Phone'} active={false} />
            <SystemCard name="Tasks & automations" state={`${s?.counts.open_tasks ?? 0} open`} detail="Approval required" active={(tasks.data || []).some(t => t.status === 'running')} />
          </div>
        </Panel>

        <Panel title="Mission Timeline" className="col-span-4 max-xl:col-span-7 max-md:col-span-12">
          <ul className="space-y-2.5">
            {timeline.map(t => (
              <li key={t.key} className="flex items-center gap-3 text-[13px] group">
                <span className="w-14 text-faint tabular-nums">{t.when ? new Date(t.when).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '—'}</span>
                <span className={`size-2 rounded-full ${t.dot}`} />
                <span className="flex-1 truncate text-ink" title={t.when ? new Date(t.when).toLocaleString() : undefined}>{t.title}</span>
                <span className="text-faint text-[12px]">{t.status}</span>
                {t.onCancel && <button onClick={t.onCancel} aria-label={`Cancel reminder ${t.title}`} className="text-faint hover:text-fault opacity-0 group-hover:opacity-100 focus:opacity-100">✕</button>}
              </li>
            ))}
            {!timeline.length && <li className="text-faint text-sm">Nothing coming up. Say “Hey JARVIS, remind me at 3 to call Marco”.</li>}
          </ul>
          <button className="text-[12px] text-arc mt-3 hover:underline" onClick={() => go('tasks')}>View all tasks ›</button>
        </Panel>

        <Panel title="Quick Commands" className="col-span-3 max-xl:col-span-5 max-md:col-span-12">
          <SpotlightCard spotlightColor="rgba(60, 231, 255, 0.35)" intensity={0.6} className="!bg-transparent !border-0 !p-0 !shadow-none space-y-2">
            {[
              { icon: 'mic', label: inCall ? 'End voice chat' : 'Start voice chat', run: () => (inCall ? j.endCall() : j.startCall()) },
              { icon: 'plus', label: 'Start new task', run: () => go('tasks') },
              { icon: 'chat', label: 'Open conversation', run: () => go('assistant') },
              { icon: 'speaker', label: 'Play music (Spotify)', run: () => api.runTool('media_control', { app: 'Spotify', action: 'play' }).then(r => r.status !== 'ok' && j.setNotice(r.error || 'Couldn’t start Spotify')) },
              { icon: 'activity', label: 'Executive briefing', run: briefing },
            ].map(c => (
              <button key={c.label} onClick={c.run} className="hud-row w-full flex items-center gap-3 px-3 py-2 text-[13px] text-ink hover:border-arc/60 hover:text-white">
                <Icon name={c.icon} className="size-4 text-arc" />{c.label}
              </button>
            ))}
          </SpotlightCard>
        </Panel>
      </div>

      {/* row 3 */}
      <div className="grid grid-cols-12 gap-4">
        <Panel title="System Monitor" className="col-span-4 max-lg:col-span-12">
          <div className="flex justify-around">
            <Ring label="CPU" value={sys.data?.cpu ?? null} />
            <Ring label="RAM" value={sys.data?.ram ?? null} />
            <Ring label="DISK" value={sys.data?.disk ?? null} />
          </div>
          <p className="text-[12px] text-faint text-center mt-2">
            {sys.data?.battery ? `Battery ${sys.data.battery.percent}%${sys.data.battery.plugged ? ' · charging' : ''} · ` : ''}
            {sys.data ? `Up ${sys.data.uptime_h} h · network ${sys.data.network ? 'online' : 'offline'}` : ''}
          </p>
        </Panel>

        <Panel title="Memory Insights" className="col-span-4 max-lg:col-span-6 max-md:col-span-12">
          <div className="flex items-center gap-4">
            <Constellation n={Math.min(24, Math.max(4, mems.data?.length ?? 0))} />
            <dl className="text-[13px] space-y-1.5 shrink-0">
              <div><dt className="text-faint text-[11px]">Memories</dt><dd className="font-display text-lg text-ink"><CountUp to={s?.counts.memories ?? 0} duration={1.2} /></dd></div>
              <div><dt className="text-faint text-[11px]">Conversations</dt><dd className="font-display text-lg text-ink"><CountUp to={s?.counts.conversations ?? 0} duration={1.2} /></dd></div>
            </dl>
          </div>
          <button className="text-[12px] text-arc mt-2 hover:underline" onClick={() => go('memory')}>Open memory ›</button>
        </Panel>

        <Panel title="LLM Status" className="col-span-4 max-lg:col-span-6 max-md:col-span-12">
          <ul className="space-y-2">
            <Row icon="overview" name="Active model" value={s?.brain.model || (s?.brain.ready ? 'Hermes default' : 'Not connected')} tone={s?.brain.ready ? 'ok' : 'bad'} />
            <Row icon="mic" name="Speech (ElevenLabs Scribe + TTS)" value={s?.voice.elevenlabs ? 'Connected' : 'Not linked'} tone={s?.voice.elevenlabs ? 'ok' : 'off'} />
            <Row icon="computer" name="Wake word (on this Mac)" value={j.wake.status === 'listening' || j.wake.status === 'paused' ? 'Running locally' : j.wake.status === 'error' ? (j.wake.detail || 'Error') : 'Off'} tone={j.wake.status === 'error' ? 'warn' : j.wake.status === 'off' ? 'off' : 'ok'} />
          </ul>
          <button className="text-[12px] text-arc mt-3 hover:underline" onClick={() => go('settings')}>Manage providers ›</button>
        </Panel>
      </div>

      {/* talk bar */}
      <div className="sticky bottom-0 pt-1 pb-1">
        <div className="hud !bg-[#04101a] flex items-center gap-4 px-4 py-2.5">
          <span className="text-[12px] text-dim flex items-center gap-2 max-md:hidden"><span className={`size-2 rounded-full ${sys.data?.network ? 'bg-ok' : 'bg-faint'}`} />Network {sys.data?.network ? 'online' : '—'}</span>
          <div className="flex-1 flex justify-center">
            <button onClick={() => (inCall ? j.endCall() : j.startCall())} aria-pressed={inCall}
              className={`talk-btn flex items-center gap-4 px-6 py-2 max-md:px-4 whitespace-nowrap rounded-full border ${inCall ? 'border-arc text-white' : 'border-arc/50 text-ink'}`}>
              <Wave active={inCall} bars={10} className="h-6 max-md:hidden" />
              <span className="text-center">
                <span className="block font-display tracking-[0.2em] text-[14px]"><ShinyText text={inCall ? 'END CONVERSATION' : 'TALK TO JARVIS'} color="#cfefff" shineColor="#ffffff" speed={3} /></span>
                <span className="block text-[11px] text-dim">{talkLabel}</span>
              </span>
              <Wave active={inCall} bars={10} className="h-6 max-md:hidden" />
            </button>
          </div>
          <button onClick={briefing} className="hud-chip text-ink hover:text-white max-md:hidden">▷ Executive briefing</button>
        </div>
        {j.notice && <p className="text-amber text-sm mt-2 text-center" role="alert">{j.notice}</p>}
      </div>
    </div>
  )
}

function Constellation({ n }: { n: number }) {
  // A gently drifting star map; one star per memory (up to 24).
  const pts = Array.from({ length: n }, (_, i) => {
    const a = i * 2.399, r = 8 + (i % 7) * 6
    return [60 + Math.cos(a) * r * 1.4, 40 + Math.sin(a) * r * 0.8]
  })
  return (
    <svg viewBox="0 0 120 80" className="flex-1 h-24 constellation" aria-hidden>
      {pts.slice(1).map((p, i) => <line key={i} x1={pts[i][0]} y1={pts[i][1]} x2={p[0]} y2={p[1]} stroke="#3CE7FF" strokeOpacity=".25" strokeWidth=".6" />)}
      {pts.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={i % 4 === 0 ? 1.8 : 1.1} fill="#3CE7FF" className="twinkle" style={{ animationDelay: `${(i % 6) * 0.4}s` }} />)}
    </svg>
  )
}
