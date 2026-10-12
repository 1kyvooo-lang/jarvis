import type { ButtonHTMLAttributes, ReactNode } from 'react'

export type CoreState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'acting' | 'stopped' | 'offline'

const coreColor: Record<CoreState, string> = {
  idle: '#3CE7FF', listening: '#3CE7FF', thinking: '#2F7BFF', speaking: '#3CE7FF',
  acting: '#FFB547', stopped: '#FF5A6A', offline: '#56616D',
}

/** The arc-reactor core: the single expressive element of the interface. */
export function Core({ state, size = 220 }: { state: CoreState; size?: number }) {
  const c = coreColor[state]
  const ticks = Array.from({ length: 60 })
  return (
    <svg className="core" data-state={state} width={size} height={size} viewBox="0 0 200 200" role="img"
      aria-label={`Assistant ${state}`}>
      <defs>
        <radialGradient id="glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={c} stopOpacity="0.55" />
          <stop offset="45%" stopColor={c} stopOpacity="0.12" />
          <stop offset="100%" stopColor={c} stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="100" cy="100" r="98" fill="url(#glow)" />
      <circle className="ripple" cx="100" cy="100" r="60" fill="none" stroke={c} strokeWidth="1" />
      <g className="core-ring r1">
        {ticks.map((_, i) => (
          <line key={i} x1="100" y1="10" x2="100" y2={i % 5 === 0 ? 20 : 15} stroke={c} strokeOpacity={i % 5 === 0 ? 0.9 : 0.35}
            strokeWidth={i % 5 === 0 ? 1.6 : 1} transform={`rotate(${i * 6} 100 100)`} />
        ))}
      </g>
      <g className="core-ring r2">
        <circle cx="100" cy="100" r="66" fill="none" stroke="#2F7BFF" strokeOpacity="0.8" strokeWidth="2"
          strokeDasharray="70 34" strokeLinecap="round" />
        <circle cx="100" cy="100" r="56" fill="none" stroke={c} strokeOpacity="0.5" strokeWidth="1" strokeDasharray="2 6" />
      </g>
      {Array.from({ length: 10 }).map((_, i) => (
        <rect key={i} x="96" y="58" width="8" height="12" rx="2" fill={c} fillOpacity="0.75" transform={`rotate(${i * 36} 100 100)`} />
      ))}
      <g className="heart">
        <circle cx="100" cy="100" r="30" fill="#000" stroke={c} strokeWidth="2.5" />
        <circle cx="100" cy="100" r="18" fill={c} fillOpacity="0.9" />
        <circle cx="100" cy="100" r="8" fill="#fff" fillOpacity="0.9" />
      </g>
    </svg>
  )
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { tone?: 'primary' | 'quiet' | 'danger' | 'amber'; size?: 'sm' | 'md' }
export function Button({ tone = 'quiet', size = 'md', className = '', ...p }: BtnProps) {
  const tones = {
    primary: 'bg-arc text-black hover:bg-white shadow-[0_0_24px_-6px_#3CE7FF]',
    quiet: 'bg-plate text-ink border border-seam hover:border-dim',
    danger: 'bg-transparent text-fault border border-fault/50 hover:bg-fault/10',
    amber: 'bg-amber text-black hover:bg-white',
  }
  const sizes = { sm: 'h-8 px-3 text-[13px]', md: 'h-10 px-4 text-sm' }
  return <button {...p} className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:opacity-40 disabled:pointer-events-none ${tones[tone]} ${sizes[size]} ${className}`} />
}

export function Dot({ tone }: { tone: 'ok' | 'warn' | 'bad' | 'off' }) {
  const c = { ok: 'bg-ok shadow-[0_0_10px_#4be3a2]', warn: 'bg-amber shadow-[0_0_10px_#FFB547]', bad: 'bg-fault shadow-[0_0_10px_#FF5A6A]', off: 'bg-faint' }[tone]
  return <span className={`inline-block size-2 rounded-full ${c}`} aria-hidden />
}

export function Pill({ children, tone = 'dim' }: { children: ReactNode; tone?: 'dim' | 'arc' | 'amber' | 'fault' | 'ok' }) {
  const c = {
    dim: 'text-dim border-seam', arc: 'text-arc border-arc/40', amber: 'text-amber border-amber/50',
    fault: 'text-fault border-fault/50', ok: 'text-ok border-ok/40',
  }[tone]
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[12px] leading-none h-6 ${c}`}>{children}</span>
}

export function PageHead({ title, sub, children }: { title: string; sub?: string; children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 mb-6">
      <div>
        <h1 className="font-display text-[28px] font-semibold tracking-tight">{title}</h1>
        {sub && <p className="text-dim mt-1 max-w-[62ch]">{sub}</p>}
      </div>
      <div className="flex gap-2">{children}</div>
    </header>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-dim text-sm py-10 text-center">{children}</div>
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-sm text-ink mb-1.5">{label}</span>
      {children}
      {hint && <span className="block text-[13px] text-faint mt-1">{hint}</span>}
    </label>
  )
}

export const inputCls = 'w-full h-10 rounded-lg bg-black border border-seam px-3 text-ink placeholder:text-faint focus:border-arc/70 outline-none'

export function statusTone(s: string): 'dim' | 'arc' | 'amber' | 'fault' | 'ok' {
  if (['ok', 'completed', 'done', 'executed', 'approved'].includes(s)) return 'ok'
  if (['pending', 'proposed', 'awaiting_approval', 'pending_approval'].includes(s)) return 'amber'
  if (['error', 'failed', 'denied'].includes(s)) return 'fault'
  if (['running', 'queued'].includes(s)) return 'arc'
  return 'dim'
}

export function Icon({ name, className = 'size-[18px]' }: { name: string; className?: string }) {
  const p: Record<string, ReactNode> = {
    overview: <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" /></>,
    chat: <path d="M4 5h16v11H9l-5 4z" />,
    memory: <><path d="M6 4h12v16l-6-4-6 4z" /></>,
    tasks: <><path d="M4 6h3M4 12h3M4 18h3M10 6h10M10 12h10M10 18h10" /></>,
    computer: <><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></>,
    activity: <path d="M3 12h4l3-7 4 14 3-7h4" />,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1" /></>,
    mic: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>,
    send: <path d="M4 12 20 4l-6 16-3-7z" />,
    stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
    speaker: <><path d="M4 9h4l5-4v14l-5-4H4z" /><path d="M16 9a4 4 0 0 1 0 6" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    trash: <path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13" />,
    power: <><path d="M12 3v8" /><path d="M6.3 7a8 8 0 1 0 11.4 0" /></>,
    phone: <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z" />,
  }
  return <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>{p[name]}</svg>
}
