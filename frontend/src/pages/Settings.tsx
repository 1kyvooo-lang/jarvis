import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api'
import type { AgentTool, ElevenVoice, GoogleInfo, Integration, Permissions, PhoneSettings, Receptionist, Settings, Status, UpdateInfo } from '../api'
import { Button, Field, PageHead, Pill, inputCls } from '../ui'
import { makeVoice } from '../voice'

const BROWSER_ASKABLE = ['browser_fill_form', 'browser_file_upload', 'browser_drop', 'browser_evaluate', 'browser_run_code_unsafe', 'browser_handle_dialog']

export default function SettingsPage({ status, onChange }: { status: Status | null; onChange: () => void }) {
  const [s, setS] = useState<Settings | null>(null)
  const [integrations, setIntegrations] = useState<Integration[]>([])
  const [perms, setPerms] = useState<Permissions | null>(null)
  const [tools, setTools] = useState<AgentTool[]>([])
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null)
  const [elKey, setElKey] = useState('')
  const [voices, setVoices] = useState<ElevenVoice[]>([])
  const [models, setModels] = useState<{ model_id: string; name: string }[]>([])
  const [sysVoices, setSysVoices] = useState<SpeechSynthesisVoice[]>([])
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    api.settings().then(r => { setS(r.settings); setIntegrations(r.integrations) })
    api.permissions().then(setPerms)
    api.agentTools().then(r => setTools(r.tools)).catch(() => {})
    const load = () => setSysVoices('speechSynthesis' in window ? speechSynthesis.getVoices() : [])
    load()
    if ('speechSynthesis' in window) speechSynthesis.onvoiceschanged = load
  }, [])
  useEffect(() => {
    if (!status?.voice.elevenlabs) return
    api.voices().then(r => setVoices(r.voices)).catch(e => flash((e as Error).message, true))
    api.voiceModels().then(r => setModels(r.models)).catch(() => {})
  }, [status?.voice.elevenlabs])

  const flash = (text: string, bad = false) => { setMsg({ text, bad }); if (!bad) setTimeout(() => setMsg(null), 2500) }
  const act = async (name: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(name)
    try { await fn(); flash(ok); onChange() } catch (e) { flash((e as Error).message, true) } finally { setBusy(null) }
  }
  const save = (part: Partial<Settings>, ok = 'Saved') => act('save', async () => { const r = await api.saveSettings(part); setS(r.settings); dispatchEvent(new Event('jarvis:settings')) }, ok)
  const savePerms = () => perms && act('perms', async () => { setPerms(await api.savePermissions(perms)); setTools((await api.agentTools()).tools) }, 'Permissions saved')

  const testVoice = useMemo(() => () => {
    if (!s) return
    const kit = makeVoice(!!status?.voice.elevenlabs && s.voice.provider !== 'browser', s.voice.browser_voice_name, s.voice.rate)
    kit.speaker.speak('Good evening. All systems are online.', () => {}).catch(e => flash((e as Error).message, true))
  }, [s, status?.voice.elevenlabs])

  if (!s || !perms) return <div className="p-8 text-dim">Loading settings…</div>
  const b = status?.brain
  const lines = (v: string[]) => v.join('\n')
  const parse = (v: string) => v.split(/[\n,]/).map(x => x.trim()).filter(Boolean)
  const toggle = (list: string[], name: string, on: boolean) => on ? [...new Set([...list, name])] : list.filter(x => x !== name)

  return (
    <div className="px-8 py-8 max-w-[900px] mx-auto">
      <PageHead title="Settings" sub="Everything here stays on this Mac." />
      {msg && <p className={`mb-4 text-sm ${msg.bad ? 'text-fault' : 'text-ok'}`} role="status">{msg.text}</p>}
      <UpdateSection />

      <Section title="You">
        <div className="flex flex-wrap gap-3 items-end">
          <Field label="Your name" hint="Used in greetings and given to Hermes."><input className={inputCls + ' w-72'} value={s.user_name} onChange={e => setS({ ...s, user_name: e.target.value })} /></Field>
          <Button tone="primary" onClick={() => save({ user_name: s.user_name })}>Save</Button>
        </div>
      </Section>

      <Section title="Hermes (the brain)">
        <p className="text-sm mb-1">{b?.ready ? <>Online{b.model ? <> · <b className="font-display">{b.model}</b></> : null}</> : <span className="text-fault">Offline</span>}</p>
        {!b?.ready && b?.detail && <pre className="text-[12.5px] text-dim whitespace-pre-wrap bg-black border border-seam rounded-lg p-3 my-2">{b.detail}</pre>}
        <p className="text-sm text-dim mb-4">Model and provider are managed by Hermes itself. JARVIS gives Hermes no terminal or file-writing tools — only the JARVIS tools below, with your approvals.</p>
        <div className="flex flex-wrap gap-2">
          <Button tone="primary" disabled={!!busy} onClick={() => act('model', api.hermesSetup, status?.platform === 'darwin' ? 'Opened the Hermes model picker in Terminal' : 'Run: hermes model')}>Choose AI model</Button>
          <Button disabled={!!busy} onClick={() => act('restart', api.hermesRestart, 'Hermes restarted')}>{busy === 'restart' ? 'Restarting…' : 'Restart Hermes'}</Button>
        </div>
        <details className="mt-5">
          <summary className="text-sm text-dim cursor-pointer">Advanced</summary>
          <div className="grid md:grid-cols-2 gap-4 mt-3">
            <Field label="API key of an existing gateway" hint="Only if you run your own Hermes gateway with its own API_SERVER_KEY.">
              <input className={inputCls} type="password" autoComplete="off" value={s.hermes.api_key} onChange={e => setS({ ...s, hermes: { ...s.hermes, api_key: e.target.value } })} />
            </Field>
            <Field label="Hermes command" hint="Leave blank to find it automatically.">
              <input className={inputCls} placeholder="~/.local/bin/hermes" value={s.hermes.binary} onChange={e => setS({ ...s, hermes: { ...s.hermes, binary: e.target.value } })} />
            </Field>
          </div>
          <Button className="mt-3" onClick={() => save({ hermes: s.hermes })}>Save</Button>
        </details>
      </Section>

      <Section title="Voice">
        {status?.voice.elevenlabs ? (
          <div className="flex flex-wrap items-center gap-3 mb-5">
            <p className="text-sm flex-1">ElevenLabs connected (key {status.voice.key_hint}{status.voice.key_source === 'keychain' ? ', in your Keychain' : ''}).</p>
            {status.voice.key_source !== 'env' && <Button size="sm" tone="danger" onClick={() => act('delkey', api.deleteElevenLabsKey, 'ElevenLabs key removed')}>Remove key</Button>}
          </div>
        ) : (
          <div className="mb-5">
            <p className="text-sm text-dim mb-2">Add your ElevenLabs key for natural speech in and out. Without it, JARVIS uses your browser’s basic voice.</p>
            <div className="flex flex-wrap gap-2">
              <input className={inputCls + ' flex-1 min-w-[260px]'} type="password" autoComplete="off" placeholder="ElevenLabs API key" value={elKey} onChange={e => setElKey(e.target.value)} />
              <Button tone="primary" disabled={elKey.length < 10 || !!busy} onClick={() => act('key', async () => { await api.setElevenLabsKey(elKey.trim()); setElKey('') }, 'ElevenLabs connected')}>{busy === 'key' ? 'Checking…' : 'Connect'}</Button>
            </div>
          </div>
        )}
        <div className="grid md:grid-cols-2 gap-4">
          {status?.voice.elevenlabs ? (<>
            <Field label="Voice" hint="Your ElevenLabs voices, including any you’ve cloned.">
              <select className={inputCls} value={s.voice.voice_id} onChange={e => setS({ ...s, voice: { ...s.voice, voice_id: e.target.value, voice_name: voices.find(v => v.voice_id === e.target.value)?.name || '' } })}>
                <option value="">George (default)</option>
                {voices.map(v => <option key={v.voice_id} value={v.voice_id}>{v.name}{v.labels?.accent ? ` · ${v.labels.accent}` : ''}{v.category === 'cloned' ? ' · yours' : ''}</option>)}
              </select>
            </Field>
            <Field label="Speech model" hint="Leave on default unless you want a faster or newer model.">
              <select className={inputCls} value={s.voice.tts_model} onChange={e => setS({ ...s, voice: { ...s.voice, tts_model: e.target.value } })}>
                <option value="">Default (Multilingual v2)</option>
                {models.map(m => <option key={m.model_id} value={m.model_id}>{m.name}</option>)}
              </select>
            </Field>
            <Field label="Your language" hint="For speech recognition. Blank = detect automatically.">
              <input className={inputCls} placeholder="e.g. en, it, fr" value={s.voice.stt_language} onChange={e => setS({ ...s, voice: { ...s.voice, stt_language: e.target.value } })} />
            </Field>
            <Field label="Use">
              <select className={inputCls} value={s.voice.provider} onChange={e => setS({ ...s, voice: { ...s.voice, provider: e.target.value as 'elevenlabs' | 'browser' } })}>
                <option value="elevenlabs">ElevenLabs</option><option value="browser">Browser voice (offline, free)</option>
              </select>
            </Field>
          </>) : (
            <Field label="Browser voice">
              <select className={inputCls} value={s.voice.browser_voice_name} onChange={e => setS({ ...s, voice: { ...s.voice, browser_voice_name: e.target.value } })}>
                <option value="">System default</option>
                {sysVoices.map(v => <option key={v.name} value={v.name}>{v.name} ({v.lang})</option>)}
              </select>
            </Field>
          )}
          <label className="flex items-center gap-3 text-sm self-end pb-2"><input type="checkbox" className="accent-[#3CE7FF] size-4" checked={s.voice.auto_speak} onChange={e => setS({ ...s, voice: { ...s.voice, auto_speak: e.target.checked } })} /> Speak every reply (voice questions always get spoken answers)</label>
        </div>
        <div className="flex gap-2 mt-5">
          <Button tone="primary" onClick={() => save({ voice: s.voice })}>Save voice</Button>
          <Button onClick={testVoice}>Test voice</Button>
        </div>
        <p className="text-[13px] text-faint mt-3">Talk with push-to-talk on the Assistant page. A hands-free “Jarvis” wake word isn’t built yet.</p>
      </Section>

      <PhoneSection status={status} onChange={onChange} />

      <GoogleSection />
      <ReceptionistSection r={s.receptionist} phoneOn={!!status?.phone.configured} googleOn={!!status?.google?.connected}
        onSave={r => save({ receptionist: r }, 'Receptionist settings saved')} />

      <Section title="“Hey JARVIS” wake word">
        <p className="text-sm text-dim mb-4">While the JARVIS window is open (it can be in the background), he listens for “Hey JARVIS” right here on your Mac, then asks what you need and talks with you hands-free. Nothing is recorded or sent anywhere until you’ve said the wake word.</p>
        <div className="grid md:grid-cols-2 gap-4">
          <label className="flex items-center gap-3 text-sm"><input type="checkbox" className="accent-[#3CE7FF] size-4" checked={s.wake.enabled} onChange={e => setS({ ...s, wake: { ...s.wake, enabled: e.target.checked } })} /> Listen for “Hey JARVIS”</label>
          <label className="flex items-center gap-3 text-sm"><input type="checkbox" className="accent-[#3CE7FF] size-4" checked={s.wake.open_at_login} onChange={e => setS({ ...s, wake: { ...s.wake, open_at_login: e.target.checked } })} /> Open the JARVIS window at login so he’s always listening</label>
          <Field label="What he says when he wakes up"><input className={inputCls} value={s.wake.greeting} onChange={e => setS({ ...s, wake: { ...s.wake, greeting: e.target.value } })} /></Field>
          <Field label={`Sensitivity (${Math.round((1 - s.wake.threshold) * 100)}%)`} hint="Higher hears you from further away but may wake by mistake.">
            <input type="range" min={0.2} max={0.85} step={0.05} value={1.05 - s.wake.threshold} onChange={e => setS({ ...s, wake: { ...s.wake, threshold: Math.round((1.05 - Number(e.target.value)) * 100) / 100 } })} className="w-full accent-[#3CE7FF]" />
          </Field>
        </div>
        <div className="mt-4"><Button tone="primary" onClick={() => save({ wake: s.wake }, 'Wake word settings saved — reopen the JARVIS window to apply sensitivity')}>Save</Button></div>
      </Section>

      <Section title="Browser (Playwright)">
        <p className="text-sm text-dim mb-4">JARVIS browses in its own Chrome window with its own sign-ins. Reading pages never asks. These always ask first:</p>
        <div className="grid sm:grid-cols-2 gap-2 mb-4">
          {BROWSER_ASKABLE.map(t => (
            <label key={t} className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-[#FFB547] size-4" checked={perms.browser.always_ask.includes(t)}
              onChange={e => setPerms({ ...perms, browser: { ...perms.browser, always_ask: toggle(perms.browser.always_ask, t, e.target.checked) } })} />
              <span className="font-display">{t.replace('browser_', '').replace(/_/g, ' ')}</span></label>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm mb-4"><input type="checkbox" className="accent-[#FFB547] size-4" checked={perms.browser.ask_outside_approved_domains}
          onChange={e => setPerms({ ...perms, browser: { ...perms.browser, ask_outside_approved_domains: e.target.checked } })} /> Ask before opening sites that aren’t on my approved list</label>
        <Field label="Clicks that ask first" hint="If a button or link mentions any of these words (buy, pay, send…), JARVIS asks before clicking. Comma or one per line.">
          <textarea className={inputCls + ' h-24 py-2'} defaultValue={perms.browser.risky_words.join(', ')} onBlur={e => setPerms({ ...perms, browser: { ...perms.browser, risky_words: parse(e.target.value) } })} />
        </Field>
        <label className="flex items-center gap-2 text-sm mt-4"><input type="checkbox" className="accent-[#3CE7FF] size-4" checked={s.browser.headless}
          onChange={e => setS({ ...s, browser: { headless: e.target.checked } })} /> Browse invisibly in the background (takes effect after restarting Hermes)</label>
        <div className="flex gap-2 mt-5">
          <Button tone="primary" onClick={async () => { await savePerms(); await save({ browser: s.browser }, 'Browser settings saved') }}>Save browser settings</Button>
        </div>
      </Section>

      <Section title="Apps, sites and folders" foot={<Button tone="primary" onClick={savePerms}>Save permissions</Button>}>
        <p className="text-sm text-dim mb-4">The Mac agent re-reads these on every request and refuses anything outside them, whatever the AI asks for.</p>
        <div className="grid md:grid-cols-3 gap-4 mb-6">
          <Field label="Approved apps" hint="One per line, exact app name."><textarea className={inputCls + ' h-40 py-2'} defaultValue={lines(perms.approved_apps)} onBlur={e => setPerms({ ...perms, approved_apps: parse(e.target.value) })} /></Field>
          <Field label="Approved websites" hint="Domain; subdomains included."><textarea className={inputCls + ' h-40 py-2'} defaultValue={lines(perms.approved_domains)} onBlur={e => setPerms({ ...perms, approved_domains: parse(e.target.value) })} /></Field>
          <Field label="Approved folders" hint="Files outside these can’t be searched or read."><textarea className={inputCls + ' h-40 py-2'} defaultValue={lines(perms.approved_directories)} onBlur={e => setPerms({ ...perms, approved_directories: parse(e.target.value) })} /></Field>
        </div>
        <table className="w-full text-sm">
          <thead className="text-faint text-left"><tr><th className="font-normal py-2">Mac tool</th><th className="font-normal py-2 w-36">Ask me first</th><th className="font-normal py-2 w-28">Enabled</th></tr></thead>
          <tbody>
            {tools.map(t => (
              <tr key={t.name} className="border-t border-seam/60">
                <td className="py-2"><span className="font-display">{t.name}</span>{t.mac_only && <span className="text-faint text-[12px]"> · macOS</span>}</td>
                <td className="py-2">{t.sensitive ? <Pill tone="amber">always</Pill> :
                  <input type="checkbox" className="accent-[#FFB547] size-4" aria-label={`${t.name} requires approval`} checked={perms.approval_required.includes(t.name)}
                    onChange={e => setPerms({ ...perms, approval_required: toggle(perms.approval_required, t.name, e.target.checked) })} />}</td>
                <td className="py-2"><input type="checkbox" className="accent-[#3CE7FF] size-4" aria-label={`${t.name} enabled`} checked={!perms.disabled_tools.includes(t.name)}
                  onChange={e => setPerms({ ...perms, disabled_tools: toggle(perms.disabled_tools, t.name, !e.target.checked) })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Memory">
        <div className="flex flex-wrap gap-6 items-end">
          <label className="flex items-center gap-3 text-sm pb-2"><input type="checkbox" className="accent-[#3CE7FF] size-4" checked={s.memory.auto_retrieve} onChange={e => setS({ ...s, memory: { ...s.memory, auto_retrieve: e.target.checked } })} /> Give Hermes relevant notes each turn</label>
          <Field label="Max notes per turn"><input type="number" min={0} max={50} className={inputCls + ' w-28'} value={s.memory.max_items} onChange={e => setS({ ...s, memory: { ...s.memory, max_items: Number(e.target.value) } })} /></Field>
          <Button tone="primary" onClick={() => save({ memory: s.memory })}>Save</Button>
        </div>
        <p className="text-[13px] text-faint mt-3">Hermes also keeps its own long-term memory, managed by Hermes.</p>
      </Section>

      <Section title="Startup and quitting">
        <p className="text-sm text-dim mb-3">The installer can start JARVIS at login so it’s always ready; open the JARVIS app any time to bring the window back. To turn login start on or off, run in Terminal from the JARVIS folder:</p>
        <pre className="bg-black border border-seam rounded-lg p-3 text-sm text-arc mb-4">./scripts/launchagent.sh install     # start at login{'\n'}./scripts/launchagent.sh uninstall   # don’t</pre>
        <Button tone="danger" onClick={() => { if (confirm('Quit JARVIS? Hermes, the Mac agent and the dashboard will stop.')) api.shutdown().then(() => flash('JARVIS is shutting down. Open the JARVIS app to start it again.')) }}>Quit JARVIS</Button>
      </Section>

      <Section title="Integrations">
        <ul className="divide-y divide-seam/60">
          {integrations.map(i => (
            <li key={i.key} className="py-2.5 flex flex-wrap items-center gap-3">
              <span className="flex-1">{i.name}{i.note && <span className="text-faint text-[13px]"> — {i.note}</span>}</span>
              <Pill tone={i.implemented ? 'ok' : 'dim'}>{i.state}</Pill>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Security">
        <ul className="text-sm text-dim space-y-1.5 list-disc pl-5">
          <li>Dashboard, Hermes’s API and the Mac agent listen on 127.0.0.1 only; other machines are refused.</li>
          <li>Hermes’s API requires a key JARVIS generated (stored in the JARVIS data folder, readable only by you).</li>
          <li>Hermes gets no shell, no file-writing and no code tools through JARVIS.</li>
          <li>API keys are kept in your macOS Keychain and never sent to the browser.</li>
          <li>The emergency stop in the left rail halts every action and queued automation instantly.</li>
        </ul>
      </Section>
    </div>
  )
}

function Section({ title, children, foot }: { title: string; children: ReactNode; foot?: ReactNode }) {
  return (
    <section className="panel p-6 mb-6">
      <h2 className="font-display text-lg mb-4">{title}</h2>
      {children}
      {foot && <div className="mt-5">{foot}</div>}
    </section>
  )
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function GoogleSection() {
  const [g, setG] = useState<GoogleInfo | null>(null)
  const [secret, setSecret] = useState('')
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null)
  const [showHow, setShowHow] = useState(false)
  useEffect(() => { api.google().then(setG).catch(() => {}) }, [])
  if (!g) return null
  const st = g.status, set = g.settings
  const upd = (p: Partial<GoogleInfo['settings']>) => setG({ ...g, settings: { ...set, ...p } })
  const saveAll = async () => {
    setMsg(null)
    try { setG(await api.saveGoogle({ ...set, ...(secret ? { client_secret: secret } : {}) })); setSecret(''); setMsg({ text: 'Saved' }) }
    catch (e) { setMsg({ text: (e as Error).message, bad: true }) }
  }
  const bh = set.business_hours
  return (
    <Section title="Google (Gmail + Calendar)">
      <div className="flex items-center gap-2 text-sm mb-4">
        <span className={`size-2 rounded-full ${st.connected ? 'bg-ok' : 'bg-faint'}`} aria-hidden />
        {st.connected ? <span>Connected as <b>{st.email || 'your account'}</b></span> : <span className="text-dim">Not connected</span>}
      </div>
      <p className="text-sm text-dim mb-3">JARVIS reads, sorts and drafts email, checks your calendar and books appointments. Sending email, and invites to other people, always waits for your OK. He can’t delete mail.</p>
      <button className="text-sm text-arc hover:underline mb-3" onClick={() => setShowHow(!showHow)} aria-expanded={showHow}>{showHow ? 'Hide the steps' : 'How to get a Google client ID (5 minutes, once)'}</button>
      {showHow && (
        <ol className="text-sm text-dim list-decimal pl-5 space-y-1.5 mb-4">
          <li>Open <b>console.cloud.google.com</b>, create a project (any name, e.g. “JARVIS”).</li>
          <li><b>APIs &amp; Services → Library</b>: enable <b>Gmail API</b> and <b>Google Calendar API</b>.</li>
          <li><b>OAuth consent screen</b>: External, app name “JARVIS”, your email; add yourself as a test user. Then click <b>Publish app</b> (so access doesn’t expire after 7 days; Google will show an “unverified app” warning for your own app — that’s expected).</li>
          <li><b>Credentials → Create credentials → OAuth client ID → Desktop app</b>. Copy the <b>Client ID</b> and <b>Client secret</b> here.</li>
          <li>Click <b>Save</b>, then <b>Connect Google</b> and allow access.</li>
        </ol>
      )}
      <div className="grid md:grid-cols-2 gap-4">
        <Field label="Client ID"><input className={inputCls} placeholder="….apps.googleusercontent.com" value={set.client_id} onChange={e => upd({ client_id: e.target.value.trim() })} /></Field>
        <Field label="Client secret" hint={st.client_configured ? 'Saved in Keychain. Paste to replace.' : undefined}>
          <input className={inputCls} type="password" autoComplete="off" placeholder={st.client_configured ? '••••••••' : 'GOCSPX-…'} value={secret} onChange={e => setSecret(e.target.value)} /></Field>
      </div>
      <h3 className="text-sm text-ink mt-5 mb-2">Working hours (for appointments)</h3>
      <div className="flex flex-wrap gap-2 mb-3">
        {DAYS.map((d, i) => {
          const on = bh.days.includes(i + 1)
          return <button key={d} aria-pressed={on} onClick={() => upd({ business_hours: { ...bh, days: on ? bh.days.filter(x => x !== i + 1) : [...bh.days, i + 1].sort() } })}
            className={`h-8 px-3 rounded-lg border text-[13px] ${on ? 'border-arc text-arc bg-arc/10' : 'border-seam text-dim'}`}>{d}</button>
        })}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Field label="From"><input type="time" className={inputCls} value={bh.start} onChange={e => upd({ business_hours: { ...bh, start: e.target.value } })} /></Field>
        <Field label="Until"><input type="time" className={inputCls} value={bh.end} onChange={e => upd({ business_hours: { ...bh, end: e.target.value } })} /></Field>
        <Field label="Slot every (min)"><input type="number" min={10} max={240} className={inputCls} value={set.slot_minutes} onChange={e => upd({ slot_minutes: Number(e.target.value) })} /></Field>
        <Field label="Min. notice (hours)"><input type="number" min={0} max={168} className={inputCls} value={set.min_notice_hours} onChange={e => upd({ min_notice_hours: Number(e.target.value) })} /></Field>
      </div>
      <div className="flex flex-wrap gap-2 mt-5">
        <Button tone="primary" onClick={saveAll}>Save</Button>
        <Button disabled={!st.client_configured && !(set.client_id && secret)} onClick={async () => { await saveAll(); location.href = '/api/google/connect' }}>{st.connected ? 'Reconnect Google' : 'Connect Google'}</Button>
        {st.connected && <Button tone="danger" onClick={async () => setG(await api.disconnectGoogle())}>Disconnect</Button>}
      </div>
      {msg && <p className={`text-sm mt-3 ${msg.bad ? 'text-fault' : 'text-ok'}`} role="status">{msg.text}</p>}
    </Section>
  )
}

function ReceptionistSection({ r: initial, phoneOn, googleOn, onSave }: { r: Receptionist; phoneOn: boolean; googleOn: boolean; onSave: (r: Receptionist) => void }) {
  const [r, setR] = useState(initial)
  useEffect(() => setR(initial), [initial])
  const chk = (key: keyof Receptionist, label: string, hint?: string) => (
    <label className="flex items-start gap-3 text-sm">
      <input type="checkbox" className="accent-[#3CE7FF] size-4 mt-0.5" checked={!!r[key]} onChange={e => setR({ ...r, [key]: e.target.checked })} />
      <span>{label}{hint && <span className="block text-[13px] text-faint">{hint}</span>}</span>
    </label>
  )
  return (
    <Section title="Receptionist & inbox assistant">
      <p className="text-sm text-dim mb-4">
        When other people call or text your Twilio number, a separate, locked-down assistant answers for you. It can check your free slots, book
        appointments in your working hours and take messages, and nothing else: it can't see your email, files, memory or chats. You get a text for every booking and message.
        {!phoneOn && <span className="text-amber"> Set up the phone line (Phone section) first.</span>}
      </p>
      <div className="grid md:grid-cols-2 gap-4 mb-4">
        {chk('answer_others', 'Answer calls and texts from other people')}
        {chk('booking', 'Let it book appointments', googleOn ? 'Into free slots in your working hours (Google Calendar)' : 'Needs Google connected')}
        {chk('approve_by_text', 'Text me when something needs my OK', 'Reply YES 12 or NO 12 from your phone')}
        <Field label="Appointment length (min)"><input type="number" min={10} max={180} className={inputCls} value={r.appointment_minutes} onChange={e => setR({ ...r, appointment_minutes: Number(e.target.value) })} /></Field>
        <Field label="Business or your name (how it introduces itself)"><input className={inputCls} placeholder="e.g. Kyvo Studio" value={r.business_name} onChange={e => setR({ ...r, business_name: e.target.value })} /></Field>
      </div>
      <Field label="What it can tell callers" hint="Services, prices, address, opening hours — anything you're happy to share. Never put private info here.">
        <textarea rows={3} className={inputCls + ' h-auto py-2'} value={r.about} onChange={e => setR({ ...r, about: e.target.value })} />
      </Field>
      <h3 className="text-sm text-ink mt-6 mb-2">Inbox assistant (Gmail)</h3>
      <p className="text-sm text-dim mb-3">Every few minutes it sorts new email into JARVIS labels and drafts replies to real people. Drafts are only sent after you approve. {!googleOn && <span className="text-amber">Connect Google first.</span>}</p>
      <div className="grid md:grid-cols-2 gap-4">
        {chk('inbox_assistant', 'Sort new email and draft replies')}
        {chk('allow_archive', 'Allow archiving newsletters & receipts')}
        <Field label="Check every (minutes)"><input type="number" min={5} max={240} className={inputCls} value={r.inbox_minutes} onChange={e => setR({ ...r, inbox_minutes: Number(e.target.value) })} /></Field>
        <Field label="Labels (comma-separated)"><input className={inputCls} value={r.labels.join(', ')} onChange={e => setR({ ...r, labels: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })} /></Field>
      </div>
      <p className="text-[13px] text-faint mt-3">Each email it processes uses your AI model (a few cents per email, depending on the model).</p>
      <div className="mt-4"><Button tone="primary" onClick={() => onSave(r)}>Save</Button></div>
    </Section>
  )
}

function UpdateSection() {
  const [u, setU] = useState<UpdateInfo | null>(null)
  const [busy, setBusy] = useState<'check' | 'apply' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [phase, setPhase] = useState<string | null>(null)
  useEffect(() => { api.checkUpdate().then(setU).catch(() => api.update().then(setU).catch(() => {})) }, [])

  const check = async () => {
    setBusy('check'); setErr(null)
    try { setU(await api.checkUpdate()) } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  const apply = async () => {
    setBusy('apply'); setErr(null); setPhase('Downloading the new version…')
    try {
      const target = (await api.applyUpdate()).latest?.sha
      setPhase('Installing — JARVIS will restart by itself (usually 1–3 minutes)…')
      const started = Date.now()
      let wentDown = false
      while (Date.now() - started < 10 * 60_000) {
        await new Promise(r => setTimeout(r, 3000))
        try {
          const now = await api.update()
          if (wentDown || now.current === target) {
            if (now.current === target) { location.reload(); return }
            if (now.error) { setErr(now.error); return }
          }
        } catch { wentDown = true; setPhase('Restarting JARVIS…') }
      }
      setErr('The update is taking longer than expected. Reopen JARVIS in a few minutes; details are in data/logs/update.log.')
    } catch (e) { setErr((e as Error).message) } finally { setBusy(null); setPhase(null) }
  }

  const short = (sha: string | null | undefined) => sha ? sha.slice(0, 7) : 'unknown'
  return (
    <Section title="Updates">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className={`size-2 rounded-full ${u?.available ? 'bg-arc' : u?.error ? 'bg-fault' : 'bg-ok'}`} aria-hidden />
        <span className="flex-1 min-w-[220px]">
          {!u ? 'Checking for updates…'
            : u.available ? <>A new version is ready{u.latest?.message ? <span className="text-dim">: {u.latest.message}</span> : null}</>
            : u.latest ? 'JARVIS is up to date.' : <span className="text-dim">Couldn't check right now.</span>}
          <span className="block text-[13px] text-faint mt-0.5">Installed: {short(u?.current)}{u?.latest ? ` · Latest: ${short(u.latest.sha)}` : ''}</span>
        </span>
        <Button disabled={!!busy} onClick={check}>{busy === 'check' ? 'Checking…' : 'Check now'}</Button>
        <Button tone="primary" disabled={!!busy || !u?.available} onClick={apply}>{busy === 'apply' ? 'Updating…' : 'Update now'}</Button>
      </div>
      {phase && <p className="text-sm text-arc mt-3" role="status">{phase}</p>}
      {(err || (u?.error && !u.available)) && <p className="text-sm text-fault mt-3" role="status">{err || u?.error}</p>}
      <p className="text-[13px] text-faint mt-3">Updates keep your settings, chats, memory and keys. JARVIS checks for new versions on its own every few hours.</p>
    </Section>
  )
}

function PhoneSection({ status, onChange }: { status: Status | null; onChange: () => void }) {
  const [p, setP] = useState<PhoneSettings | null>(null)
  const [token, setToken] = useState('')
  const [hasCf, setHasCf] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null)
  useEffect(() => { api.phone().then(r => { setP(r.settings); setHasCf(r.cloudflared) }).catch(() => {}) }, [])
  if (!p) return null
  const st = status?.phone
  const run = async (name: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(name); setMsg(null)
    try { await fn(); setMsg({ text: ok }); onChange() } catch (e) { setMsg({ text: (e as Error).message, bad: true }) } finally { setBusy(null) }
  }
  const online = !!(st?.configured && st.public_url && st.webhooks === 'configured')
  return (
    <Section title="Phone (Twilio)">
      <p className="text-sm text-dim mb-4">Call or text your Twilio number to talk to JARVIS, and let him call or text you. Only your own number gets through. Works while this Mac is on and awake.</p>
      <div className="flex items-center gap-2 text-sm mb-5">
        <span className={`size-2 rounded-full ${online ? 'bg-ok' : st?.error ? 'bg-fault' : 'bg-faint'}`} aria-hidden />
        {online ? <span>Online — call or text <b className="font-display">{p.twilio_number}</b></span>
          : st?.error ? <span className="text-fault">{st.error}</span>
          : st?.configured ? <span className="text-dim">Connecting…</span> : <span className="text-dim">Not set up</span>}
      </div>
      {!hasCf && <p className="text-amber text-sm mb-4">Run the JARVIS installer again to add the secure tunnel (cloudflared).</p>}
      <div className="grid md:grid-cols-2 gap-4">
        <Field label="Account SID" hint="Twilio Console → Account Info"><input className={inputCls} placeholder="AC…" value={p.account_sid} onChange={e => setP({ ...p, account_sid: e.target.value.trim() })} /></Field>
        <Field label="Auth Token" hint={st?.token_hint ? `Saved in Keychain (${st.token_hint}). Paste to replace.` : 'Twilio Console → Account Info'}>
          <input className={inputCls} type="password" autoComplete="off" placeholder={st?.token_hint ? '••••••••' : '32 characters'} value={token} onChange={e => setToken(e.target.value)} /></Field>
        <Field label="Your Twilio number" hint="International format, e.g. +1 555 010 0006"><input className={inputCls} value={p.twilio_number} onChange={e => setP({ ...p, twilio_number: e.target.value })} /></Field>
        <Field label="Your mobile number" hint="The only number that can call or text JARVIS"><input className={inputCls} placeholder="+39 …" value={p.owner_number} onChange={e => setP({ ...p, owner_number: e.target.value })} /></Field>
        <Field label="Language you'll speak on calls">
          <select className={inputCls} value={p.language} onChange={e => setP({ ...p, language: e.target.value })}>
            <option value="en-GB">English (UK)</option><option value="en-US">English (US)</option><option value="it-IT">Italiano</option>
            <option value="es-ES">Español</option><option value="fr-FR">Français</option><option value="de-DE">Deutsch</option>
          </select>
        </Field>
        <label className="flex items-center gap-3 text-sm self-end pb-2"><input type="checkbox" className="accent-[#3CE7FF] size-4" checked={p.enabled} onChange={e => setP({ ...p, enabled: e.target.checked })} /> Phone line on</label>
      </div>
      <div className="flex flex-wrap gap-2 mt-5">
        <Button tone="primary" disabled={!!busy} onClick={() => run('save', async () => { await api.savePhone({ ...p, ...(token ? { auth_token: token } : {}) }); setToken('') }, 'Phone settings saved — going online…')}>{busy === 'save' ? 'Checking with Twilio…' : 'Save'}</Button>
        <Button disabled={!online || !!busy} onClick={() => run('call', api.testCall, 'Calling your phone now…')}>Call me now</Button>
        <Button disabled={!online || !!busy} onClick={() => run('sms', api.testSms, 'Text sent.')}>Send test text</Button>
      </div>
      {msg && <p className={`text-sm mt-3 ${msg.bad ? 'text-fault' : 'text-ok'}`} role="status">{msg.text}</p>}
      <p className="text-[13px] text-faint mt-4">JARVIS points your Twilio number at this Mac automatically each time it starts. On a call, say “goodbye” to hang up; if something needs your approval he’ll ask and you answer “yes” or “no”.</p>
    </Section>
  )
}
