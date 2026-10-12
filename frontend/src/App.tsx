import { useEffect, useRef, useState } from 'react'
import Lenis from 'lenis'
import { api } from './api'
import type { Status } from './api'
import { usePoll } from './hooks'
import { Dot, Icon } from './ui'
import { ApprovalTray } from './components/ApprovalTray'
import CommandCenter from './pages/CommandCenter'
import { JarvisProvider } from './engine'
import Assistant from './pages/Assistant'
import MemoryPage from './pages/Memory'
import Tasks from './pages/Tasks'
import Computer from './pages/Computer'
import ActivityPage from './pages/Activity'
import SettingsPage from './pages/Settings'
import Setup from './pages/Setup'

const NAV = [
  { id: 'overview', label: 'Command Center', icon: 'overview' },
  { id: 'assistant', label: 'Assistant', icon: 'chat' },
  { id: 'memory', label: 'Memory', icon: 'memory' },
  { id: 'tasks', label: 'Tasks', icon: 'tasks' },
  { id: 'computer', label: 'Computer', icon: 'computer' },
  { id: 'activity', label: 'Activity', icon: 'activity' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
] as const
export type PageId = (typeof NAV)[number]['id']

function readHash(): PageId {
  const h = location.hash.replace('#', '') as PageId
  return NAV.some(n => n.id === h) ? h : 'overview'
}

export default function App() {
  const [page, setPage] = useState<PageId>(readHash)
  const status = usePoll<Status>(api.status, 4000)
  const [skipSetup, setSkipSetup] = useState(() => { try { return localStorage.getItem('jarvis.setupDone') === '1' } catch { return false } })
  const finishSetup = () => { try { localStorage.setItem('jarvis.setupDone', '1') } catch { /* ignore */ } setSkipSetup(true) }

  useEffect(() => {
    const on = () => setPage(readHash())
    addEventListener('hashchange', on)
    return () => removeEventListener('hashchange', on)
  }, [])
  const go = (p: PageId) => { location.hash = p; setPage(p) }

  // Lenis smooth scrolling for the page area (off for reduced motion and the chat, which scrolls itself).
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = scroller.current
    if (!el || page === 'assistant' || matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const lenis = new Lenis({ wrapper: el, content: el.firstElementChild as HTMLElement, smoothWheel: true, lerp: 0.12 })
    let raf = 0
    const loop = (t: number) => { lenis.raf(t); raf = requestAnimationFrame(loop) }
    raf = requestAnimationFrame(loop)
    return () => { cancelAnimationFrame(raf); lenis.destroy() }
  }, [page])

  const s = status.data
  if (status.error && !s) {
    return (
      <div className="field min-h-full grid place-items-center p-8">
        <div className="panel p-8 max-w-md">
          <h1 className="font-display text-xl mb-2">Backend offline</h1>
          <p className="text-dim mb-4">The dashboard can't reach the JARVIS backend on this Mac. Start everything with:</p>
          <pre className="bg-black border border-seam rounded-lg p-3 text-arc text-sm">./scripts/dev.sh</pre>
        </div>
      </div>
    )
  }
  if (s && !skipSetup) {
    return <Setup status={s} onRefresh={() => status.refresh()} onSkip={finishSetup} />
  }

  return (
    <JarvisProvider status={s} onWake={() => go('overview')}>
    <div className="field h-full flex">
      <nav className="w-[220px] shrink-0 border-r border-seam/70 flex flex-col py-5 px-3 max-md:w-[64px]" aria-label="Main">
        <div className="flex items-center gap-2.5 px-2 mb-8">
          <img src="/core.svg" alt="" className="size-8" />
          <span className="font-display text-lg font-semibold tracking-[0.18em] max-md:hidden">JARVIS</span>
        </div>
        <ul className="space-y-1 flex-1">
          {NAV.map(n => (
            <li key={n.id}>
              <button onClick={() => go(n.id)} aria-current={page === n.id ? 'page' : undefined}
                className={`w-full flex items-center gap-3 px-3 h-10 rounded-lg text-sm transition-colors ${page === n.id
                  ? 'bg-plate text-ink shadow-[inset_2px_0_0_#3CE7FF]' : 'text-dim hover:text-ink hover:bg-graphite'}`}>
                <Icon name={n.icon} />
                <span className="max-md:hidden">{n.label}</span>
                {n.id === 'settings' && s?.update?.available &&
                  <span className="ml-auto size-2 rounded-full bg-arc max-md:hidden" title="Update available" />}
                {n.id === 'tasks' && s && s.counts.open_tasks > 0 &&
                  <span className="ml-auto text-[12px] text-faint max-md:hidden">{s.counts.open_tasks}</span>}
              </button>
            </li>
          ))}
        </ul>
        {s && (
          <div className="px-3 space-y-2 text-[13px] text-dim mb-4 max-md:hidden">
            <div className="flex items-center gap-2"><Dot tone={s.brain.ready ? 'ok' : s.brain.state === 'starting' ? 'warn' : 'bad'} /> Hermes {s.brain.ready ? 'online' : s.brain.state === 'starting' ? 'starting' : 'offline'}</div>
            <div className="flex items-center gap-2"><Dot tone={s.voice.elevenlabs ? 'ok' : 'off'} /> Voice {s.voice.elevenlabs ? 'ElevenLabs' : 'basic'}</div>
            <div className="flex items-center gap-2"><Dot tone={!s.agent.online ? 'bad' : s.agent.stopped ? 'warn' : 'ok'} /> Mac agent {s.agent.online ? (s.agent.stopped ? 'halted' : 'online') : 'offline'}</div>
          </div>
        )}
        <EmergencyButton stopped={!!s?.emergency_stop} onChange={status.refresh} />
      </nav>

      <main className="flex-1 min-w-0 flex flex-col">
        <ApprovalTray onChange={status.refresh} />
        {s && !s.brain.ready && !s.emergency_stop && (
          <div className="bg-fault/10 border-b border-fault/40 text-fault px-6 py-2.5 text-sm flex flex-wrap gap-3 items-center">
            <span className="flex-1">Hermes is offline: {s.brain.detail || 'starting…'}</span>
            <button className="underline underline-offset-4" onClick={() => go('settings')}>Fix in Settings</button>
          </div>
        )}
        {s?.emergency_stop && (
          <div className="bg-fault/10 border-b border-fault/40 text-fault px-6 py-2.5 text-sm">
            Emergency stop is on. No actions or automations will run until you resume.
          </div>
        )}
        <div ref={scroller} className="flex-1 min-h-0 overflow-y-auto">
          {page === 'overview' && <CommandCenter go={go} />}
          {page === 'assistant' && <Assistant status={s} />}
          {page === 'memory' && <MemoryPage />}
          {page === 'tasks' && <Tasks />}
          {page === 'computer' && <Computer status={s} />}
          {page === 'activity' && <ActivityPage />}
          {page === 'settings' && <SettingsPage status={s} onChange={status.refresh} />}
        </div>
      </main>
    </div>
    </JarvisProvider>
  )
}

function EmergencyButton({ stopped, onChange }: { stopped: boolean; onChange: () => void }) {
  const [busy, setBusy] = useState(false)
  const click = async () => {
    setBusy(true)
    try { await (stopped ? api.resume() : api.emergencyStop()) } finally { setBusy(false); onChange() }
  }
  return (
    <button onClick={click} disabled={busy}
      className={`flex items-center gap-2.5 justify-center h-11 rounded-lg text-sm font-medium border transition-colors ${stopped
        ? 'border-ok/50 text-ok hover:bg-ok/10' : 'border-fault/50 text-fault hover:bg-fault/10'}`}
      title={stopped ? 'Allow actions again' : 'Immediately stop all actions and automations'}>
      <Icon name="power" />
      <span className="max-md:hidden">{stopped ? 'Resume actions' : 'Emergency stop'}</span>
    </button>
  )
}
