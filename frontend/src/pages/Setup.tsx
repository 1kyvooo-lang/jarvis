import { useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api'
import type { Status } from '../api'
import { Button, Core, inputCls } from '../ui'

type Step = { done: boolean | null; title: string; body: ReactNode; action?: ReactNode }

export default function Setup({ status, onRefresh, onSkip }: { status: Status; onRefresh: () => void; onSkip: () => void }) {
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  const run = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name); setErr(null)
    try { await fn() } catch (e) { setErr((e as Error).message) } finally { setBusy(null); onRefresh() }
  }
  const b = status.brain
  const isMac = status.platform === 'darwin'

  const steps: Step[] = [
    {
      done: b.installed, title: 'Hermes Agent installed',
      body: b.installed ? 'The brain that plans and uses tools.' : 'Not found. Run “Install JARVIS” again — it installs Hermes for you.',
    },
    {
      done: b.model_configured, title: 'AI model chosen in Hermes',
      body: b.model_configured ? 'Hermes knows which model to use (Nous Portal, OpenRouter or another provider).'
        : 'Pick a provider and sign in — Hermes opens its own picker in Terminal. JARVIS restarts Hermes when you’re done.',
      action: <Button size="sm" tone={b.model_configured ? 'quiet' : 'primary'} disabled={!b.installed || !!busy}
        onClick={() => run('model', api.hermesSetup)}>{b.model_configured ? 'Change model' : isMac ? 'Choose model' : 'Show command'}</Button>,
    },
    {
      done: b.ready, title: 'Hermes running',
      body: b.ready ? `Connected${b.model ? ` · ${b.model}` : ''}.` : <span className="whitespace-pre-wrap">{b.detail || 'Starting…'}</span>,
      action: !b.ready && b.installed ? <Button size="sm" disabled={!!busy} onClick={() => run('hermes', api.hermesRestart)}>{busy === 'hermes' ? 'Restarting…' : 'Restart Hermes'}</Button> : undefined,
    },
    {
      done: status.agent.online, title: 'Mac agent running',
      body: status.agent.online ? 'JARVIS can act on this Mac within your approved apps, sites and folders.' : status.agent.error || 'Starting…',
      action: !status.agent.online ? <Button size="sm" disabled={!!busy} onClick={() => run('agent', api.agentRestart)}>Start agent</Button> : undefined,
    },
    {
      done: status.voice.elevenlabs ? true : null, title: 'ElevenLabs voice',
      body: status.voice.elevenlabs ? `Connected (key ${status.voice.key_hint}).` : (
        <span>Natural voice in and out. Paste your key from <a className="text-arc underline underline-offset-4" href="https://elevenlabs.io/app/settings/api-keys" target="_blank" rel="noreferrer">elevenlabs.io → API keys</a>. It’s stored in your Keychain.</span>),
      action: status.voice.elevenlabs ? undefined : (
        <form className="flex gap-2 mt-2 w-full" onSubmit={e => { e.preventDefault(); run('eleven', async () => { await api.setElevenLabsKey(key.trim()); setKey(''); setSaved('ElevenLabs connected.') }) }}>
          <input className={inputCls + ' h-9 flex-1'} type="password" autoComplete="off" placeholder="ElevenLabs API key" value={key}
            onChange={e => setKey(e.target.value)} aria-label="ElevenLabs API key" />
          <Button size="sm" tone="primary" disabled={key.length < 10 || !!busy}>{busy === 'eleven' ? 'Checking…' : 'Connect'}</Button>
        </form>),
    },
  ]
  const ready = b.ready && status.agent.online

  return (
    <div className="field min-h-full grid place-items-center p-6">
      <div className="w-full max-w-[980px] grid md:grid-cols-[300px_1fr] gap-10 items-center">
        <div className="justify-self-center"><Core state={ready ? 'idle' : 'offline'} size={260} /></div>
        <div>
          <h1 className="font-display text-[34px] leading-tight font-semibold mb-2">Getting JARVIS ready</h1>
          <p className="text-dim mb-6 max-w-[56ch]">This updates live. Most of it happens on its own; the model choice and voice key are yours.</p>
          <ol className="space-y-3">
            {steps.map((s, i) => (
              <li key={i} className="panel p-4 flex flex-wrap items-start gap-3">
                <span className={`mt-0.5 size-6 shrink-0 grid place-items-center rounded-full text-[12px] font-semibold ${s.done ? 'bg-ok text-black' : s.done === null ? 'border border-seam text-dim' : 'border border-amber text-amber'}`} aria-hidden>
                  {s.done ? '✓' : i + 1}
                </span>
                <div className="flex-1 min-w-[220px]">
                  <p className="font-medium">{s.title}{s.done === null && !status.voice.elevenlabs && i === 4 ? <span className="text-faint font-normal"> · optional</span> : ''}</p>
                  <div className="text-sm text-dim mt-0.5">{s.body}</div>
                </div>
                {s.action}
              </li>
            ))}
          </ol>
          {(err || saved) && <p className={`mt-4 text-sm ${err ? 'text-fault' : 'text-ok'}`} role="status">{err || saved}</p>}
          <div className="flex gap-3 mt-6">
            <Button tone="primary" disabled={!ready} onClick={onSkip}>Open JARVIS</Button>
            {!ready && <Button onClick={onSkip}>Continue anyway</Button>}
          </div>
        </div>
      </div>
    </div>
  )
}
