import { useState } from 'react'
import { api } from '../api'
import type { Activity, Status, Task } from '../api'
import type { PageId } from '../App'
import { timeAgo, usePoll } from '../hooks'
import { Button, Core, Dot, Empty, Pill, statusTone } from '../ui'
import type { CoreState } from '../ui'

function greeting(name: string) {
  const h = new Date().getHours()
  const part = h < 5 ? 'Working late' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
  return name ? `${part}, ${name}.` : `${part}.`
}

export default function Overview({ status, go }: { status: Status | null; go: (p: PageId) => void }) {
  const tasks = usePoll<Task[]>(api.tasks, 6000)
  const activity = usePoll<Activity[]>(() => api.activity(8), 5000)
  const [quick, setQuick] = useState<{ label: string; text: string; bad?: boolean } | null>(null)

  const state: CoreState = !status ? 'idle' : status.emergency_stop ? 'stopped' : !status.agent.online || !status.brain.ready ? 'offline'
    : (tasks.data?.some(t => t.status === 'running') ? 'acting' : 'idle')

  const run = async (label: string, tool: string, args: Record<string, unknown> = {}) => {
    setQuick({ label, text: 'Running…' })
    try {
      const r = await api.runTool(tool, args)
      setQuick(r.status === 'ok' ? { label, text: summarize(tool, r.output) } : { label, text: r.error || 'Failed', bad: true })
    } catch (e) { setQuick({ label, text: (e as Error).message, bad: true }) }
    activity.refresh()
  }

  const todo = (tasks.data || []).filter(t => ['todo', 'proposed', 'queued', 'running'].includes(t.status)).slice(0, 6)
  const autos = (tasks.data || []).filter(t => t.steps)
  const count = (s: string) => autos.filter(t => t.status === s).length

  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto">
      <section className="grid lg:grid-cols-[minmax(0,1fr)_340px] gap-8 items-center mb-10">
        <div className="flex items-center gap-8 max-sm:flex-col max-sm:items-start">
          <Core state={state} size={200} />
          <div>
            <h1 className="font-display text-[40px] leading-[1.05] font-semibold tracking-tight">{greeting(status?.user_name || '')}</h1>
            <p className="text-dim mt-3 max-w-[46ch]">
              {state === 'stopped' ? 'All actions are halted. Resume from the left rail when you’re ready.'
                : state === 'offline' ? (status?.brain.ready ? 'The Mac agent is offline, so I can talk but can’t act on your computer yet.' : 'Hermes is offline — open Settings → Hermes to fix it.')
                : 'Systems nominal. Ask me anything, or hand me something to do on your Mac.'}
            </p>
            <div className="flex gap-3 mt-5">
              <Button tone="primary" onClick={() => go('assistant')}>Talk to JARVIS</Button>
              <Button onClick={() => go('tasks')}>Plan a task</Button>
            </div>
          </div>
        </div>
        <dl className="panel p-5 space-y-3.5 text-sm">
          <Row label="Hermes" tone={status?.brain.ready ? 'ok' : 'bad'} value={status?.brain.ready ? (status.brain.model || 'online') : 'offline'} />
          <Row label="Voice" tone={status?.voice.elevenlabs ? 'ok' : 'off'} value={status?.voice.elevenlabs ? 'ElevenLabs' : 'browser (add ElevenLabs key)'} />
          <Row label="Browser" tone={status?.browser.available ? 'ok' : 'off'} value={status?.browser.available ? 'Playwright MCP' : 'not installed'} />
          <Row label="Mac agent" tone={!status?.agent.online ? 'bad' : status.agent.stopped ? 'warn' : 'ok'}
            value={status?.agent.online ? `${status.agent.platform} · ${status.agent.tool_count} tools` : 'offline'} />
          <Row label="Approvals" tone={status?.counts.pending_approvals ? 'warn' : 'ok'} value={`${status?.counts.pending_approvals ?? 0} waiting`} />
          
        </dl>
      </section>

      <section className="mb-10">
        <h2 className="font-display text-lg mb-3">Quick actions</h2>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => run('Time', 'get_datetime')}>What time is it</Button>
          <Button size="sm" onClick={() => run('System', 'system_status')}>System status</Button>
          <Button size="sm" onClick={() => run('OS', 'system_info', { topic: 'os' })}>macOS version</Button>
          <Button size="sm" onClick={() => run('Notify', 'notify', { title: 'JARVIS', message: 'Test notification from your dashboard.' })}>Test notification</Button>
          <Button size="sm" onClick={() => run('Safari', 'open_app', { name: 'Safari' })}>Open Safari</Button>
        </div>
        {quick && (
          <p className={`mt-3 text-sm ${quick.bad ? 'text-fault' : 'text-ink'}`} role="status">
            <span className="text-faint">{quick.label}:</span> {quick.text}
          </p>
        )}
      </section>

      <div className="grid lg:grid-cols-[1.2fr_1fr] gap-6">
        <section className="panel p-5">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="font-display text-lg">Today’s tasks</h2>
            <button className="text-sm text-arc hover:underline" onClick={() => go('tasks')}>All tasks</button>
          </div>
          {todo.length ? (
            <ul className="divide-y divide-seam/70">
              {todo.map(t => (
                <li key={t.id} className="py-2.5 flex items-center gap-3">
                  <span className="flex-1 truncate">{t.title}</span>
                  {t.due_at && <span className="text-faint text-[13px]">{new Date(t.due_at).toLocaleString(undefined, { hour: '2-digit', minute: '2-digit', day: 'numeric', month: 'short' })}</span>}
                  <Pill tone={statusTone(t.status)}>{t.status}</Pill>
                </li>
              ))}
            </ul>
          ) : <Empty>Nothing open. Ask JARVIS to add a task or plan an automation.</Empty>}
          <p className="text-[13px] text-dim mt-4 pt-3 border-t border-seam/70">
            Automations: {count('queued')} queued · {count('running')} running · {count('proposed')} awaiting approval · {count('failed')} failed
          </p>
        </section>
        <section className="panel p-5">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="font-display text-lg">Recent activity</h2>
            <button className="text-sm text-arc hover:underline" onClick={() => go('activity')}>Full log</button>
          </div>
          {activity.data?.length ? (
            <ul className="space-y-2.5">
              {activity.data.map(a => (
                <li key={a.id} className="flex items-start gap-3 text-sm">
                  <span className="mt-1.5"><Dot tone={a.status === 'ok' ? 'ok' : a.status === 'error' ? 'bad' : a.status === 'pending' ? 'warn' : 'off'} /></span>
                  <span className="flex-1 min-w-0 truncate">{a.action}</span>
                  <span className="text-faint text-[13px] shrink-0">{timeAgo(a.ts)}</span>
                </li>
              ))}
            </ul>
          ) : <Empty>No activity yet.</Empty>}
        </section>
      </div>
    </div>
  )
}

function Row({ label, value, tone }: { label: string; value: string; tone: 'ok' | 'warn' | 'bad' | 'off' }) {
  return (
    <div className="flex items-center gap-3">
      <Dot tone={tone} />
      <dt className="text-dim w-24">{label}</dt>
      <dd className="text-ink truncate">{value}</dd>
    </div>
  )
}

function summarize(tool: string, out: unknown): string {
  const o = out as Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
  if (tool === 'get_datetime') return `${o.date}, ${o.time}`
  if (tool === 'system_status') return `CPU ${o.cpu_percent}% · memory ${o.memory.used_percent}% · disk ${o.disk_home.used_percent}% used${o.battery ? ` · battery ${o.battery.percent}%` : ''}`
  if (tool === 'system_info') return o.macos ? `macOS ${o.macos} on ${o.machine}` : `${o.system} ${o.release}`
  return JSON.stringify(out)
}
