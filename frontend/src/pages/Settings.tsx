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

      <Section title="Personality">
        <p className="text-sm text-dim mb-4">How JARVIS talks to you.</p>
        <div className="grid md:grid-cols-2 gap-4">
          <Field label="Manner">
            <select className={inputCls} value={s.personality.style} onChange={e => setS({ ...s, personality: { ...s.personality, style: e.target.value as 'jarvis' | 'friendly' } })}>
              <option value="jarvis">JARVIS (Iron Man): courteous British butler, calm, dry wit</option>
              <option value="friendly">Friendly and casual</option>
            </select>
          </Field>
          <Field label="He calls you" hint="e.g. sir, ma'am, boss, or your name">
            <input className={inputCls} value={s.personality.address} onChange={e => setS({ ...s, personality: { ...s.personality, address: e.target.value } })} />
          </Field>
        </div>
        <p className="text-[13px] text-faint mt-3">His default voice is “Daniel”, a refined British ElevenLabs voice. For an even closer match, create one in ElevenLabs → Voices → <b>Voice Design</b> (e.g. “calm, refined British male AI butler, crisp and dry”) and pick it under Voice below.</p>
        <div className="mt-4"><Button tone="primary" onClick={() => save({ personality: s.personality }, 'Personality saved')}>Save</Button></div>
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

      <Section title="Morning briefing">
        <p className="text-sm text-dim mb-4">Every morning JARVIS sends you a short rundown: today's calendar, important new email, open tasks, reminders and anything waiting for your OK. Without a phone line it shows as a Mac notification.</p>
        <div className="grid md:grid-cols-3 gap-4 items-end">
          <label className="flex items-center gap-3 text-sm"><input type="checkbox" className="accent-[#3CE7FF] size-4" checked={s.briefing.enabled} onChange={e => setS({ ...s, briefing: { ...s.briefing, enabled: e.target.checked } })} /> Send me a morning briefing</label>
          <Field label="At"><input type="time" className={inputCls} value={s.briefing.time} onChange={e => setS({ ...s, briefing: { ...s.briefing, time: e.target.value } })} /></Field>
          <Field label="How">
            <select className={inputCls} value={s.briefing.via} onChange={e => setS({ ...s, briefing: { ...s.briefing, via: e.target.value as 'text' | 'call' | 'notification' } })}>
              <option value="text">Text message</option><option value="call">Phone call</option><option value="notification">Mac notification</option>
            </select>
          </Field>
        </div>
        <div className="flex flex-wrap gap-2 mt-3">
          {DAYS.map((d, i) => {
            const on = s.briefing.days.includes(i + 1)
            return <button key={d} aria-pressed={on} onClick={() => setS({ ...s, briefing: { ...s.briefing, days: on ? s.briefing.days.filter(x => x !== i + 1) : [...s.briefing.days, i + 1].sort() } })}
              className={`h-8 px-3 rounded-lg border text-[13px] ${on ? 'border-arc text-arc bg-arc/10' : 'border-seam text-dim'}`}>{d}</button>
          })}
        </div>
        <div className="flex gap-2 mt-4">
          <Button tone="primary" onClick={() => save({ briefing: s.briefing }, 'Briefing saved')}>Save</Button>
          <Button disabled={busy === 'brief'} onClick={() => act('brief', api.briefingNow, 'Briefing sent')}>{busy === 'brief' ? 'Preparing…' : 'Send one now'}</Button>
        </div>
      </Section>

      <Section title="Model router">
        <p className="text-sm text-dim mb-4">Send each message to the best model. Start a message with <b>fast:</b>, <b>think:</b>, <b>vision:</b> or <b>local:</b> to choose, or let JARVIS pick: short questions go to <b>fast</b>, long or analytical ones to <b>think</b>. Everything else uses your default Hermes model. Each provider needs its key in Hermes once (in Terminal: <code className="text-arc">hermes auth add &lt;provider&gt;</code>). For Ollama on this Mac use provider <code className="text-arc">custom</code> and URL <code className="text-arc">http://localhost:11434/v1</code>.</p>
        <div className="flex flex-wrap gap-6 mb-4">
          <label className="flex items-center gap-3 text-sm"><input type="checkbox" className="accent-[#3CE7FF] size-4" checked={s.router.enabled} onChange={e => setS({ ...s, router: { ...s.router, enabled: e.target.checked } })} /> Use the router</label>
          <label className="flex items-center gap-3 text-sm"><input type="checkbox" className="accent-[#3CE7FF] size-4" checked={s.router.auto} onChange={e => setS({ ...s, router: { ...s.router, auto: e.target.checked } })} /> Pick automatically when there's no prefix</label>
        </div>
        <div className="space-y-3">
          {([['fast', 'Quick answers', 'e.g. anthropic · claude-haiku-5-5, or groq · llama-3.3-70b-versatile'], ['think', 'Deep reasoning', 'e.g. anthropic · claude-opus-5-5'],
            ['vision', 'Images', 'e.g. gemini · gemini-2.5-pro'], ['local', 'Private, on this Mac', 'e.g. custom · llama3.2 · http://localhost:11434/v1']] as const).map(([alias, label, eg]) => {
            const r = s.router.routes[alias] || {}
            const setR = (p: Partial<typeof r>) => setS({ ...s, router: { ...s.router, routes: { ...s.router.routes, [alias]: { ...r, ...p } } } })
            return (
              <div key={alias} className="grid md:grid-cols-[110px_1fr_1fr_1fr] gap-2 items-center">
                <span className="text-sm"><b className="font-display text-arc">{alias}:</b><span className="block text-[12px] text-faint">{label}</span></span>
                <input className={inputCls} placeholder="provider" aria-label={`${alias} provider`} value={r.provider || ''} onChange={e => setR({ provider: e.target.value.trim() })} />
                <input className={inputCls} placeholder="model" aria-label={`${alias} model`} title={eg} value={r.model || ''} onChange={e => setR({ model: e.target.value.trim() })} />
                <input className={inputCls} placeholder="base URL (optional)" aria-label={`${alias} base URL`} value={r.base_url || ''} onChange={e => setR({ base_url: e.target.value.trim() })} />
              </div>
            )
          })}
        </div>
        <div className="mt-4"><Button tone="primary" onClick={() => save({ router: s.router }, 'Router saved — restarting Hermes to apply it')}>Save</Button></div>
      </Section>

      <GoogleSection />
      <ReceptionistSection r={s.receptionist} phoneOn={!!status?.phone.configured} googleOn={!!status?.google?.connected}
        onSave={r => save({ receptionist: r }, 'Receptionist settings saved')} />

      <Section title="“Hey JARVIS” wake word">
        <p className="text-sm text-dim mb-4">While the JARVIS window is open (it can be in the background), he listens for “Hey JARVIS” right here on your Mac, then asks what you need and talks with you hands-free. Nothing is recorded or sent anywhere until you’ve said the wake word.</p>
        <div className="grid md:grid-cols-2 gap-4">
          <label className="flex items-center gap-3 text-sm"><input type="checkbox" className="accent-[#3CE7FF] size-4" checked={s.wake.enabled} onChange={e => setS({ ...s, wake: { ...s.wake, enabled: e.target.checked } })} /> Listen for “Hey JARVIS”</label>
          <label className="flex items-center gap-3 text-sm"><input type="checkbox" className="accent-[#3CE7FF] size-4" checked={s.wake.open_at_login} onChange={e => setS({ ...s, wake: { ...s.wake, open_at_login: e.target.checked } })} /> Open the JARVIS window at login so he’s always listening</label>
          <Field label="What he says when he wakes up"><input className={inputCls} placeholder="Leave empty for a varied JARVIS greeting (Yes, sir? …)" value={s.wake.greeting} onChange={e => setS({ ...s, wake: { ...s.wake, greeting: e.target.value } })} /></Field>
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

      <Section title="Obsidian" foot={<Button tone="primary" onClick={savePerms}>Save</Button>}>
        <p className="text-sm text-dim mb-4">Point JARVIS at your Obsidian vault and he can search and read your notes, create new ones and add to existing ones (“Hey JARVIS, add this to my Ideas note”). Replacing a whole note always asks you first and keeps a backup.</p>
        <Field label="Vault folder" hint="The folder that contains the .obsidian folder, e.g. ~/Documents/Obsidian Vault">
          <input className={inputCls} placeholder="~/Documents/Obsidian Vault" value={perms.obsidian_vault || ''} onChange={e => setPerms({ ...perms, obsidian_vault: e.target.value })} />
        </Field>
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

      <RemoteSection />

      <BackupSection />

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
  const [advanced, setAdvanced] = useState(false)
  const [test, setTest] = useState<string | null>(null)
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
  const runTest = async () => {
    setTest('Checking Mail and Calendar… (macOS may ask you to allow JARVIS — click OK)')
    try {
      const r = await api.testMailcal()
      setTest(r.email_error || r.calendar_error ? `Problem: ${r.email_error || r.calendar_error}`
        : `Working ✓ Latest email: “${r.recent_emails?.[0] || '—'}” · ${r.events_today ?? 0} event(s) today`)
    } catch (e) { setTest((e as Error).message) }
  }
  return (
    <Section title="Google (Gmail + Calendar)">
      <div className="flex items-center gap-2 text-sm mb-4">
        <span className={`size-2 rounded-full ${st.provider ? 'bg-ok' : 'bg-faint'}`} aria-hidden />
        {st.provider === 'google' ? <span>Connected directly as <b>{st.email || 'your account'}</b></span>
          : st.provider === 'mac' ? <span>Connected through your Mac's Mail and Calendar</span>
          : <span className="text-dim">Not connected</span>}
      </div>
      <p className="text-sm text-dim mb-4">JARVIS reads, sorts and answers email, checks your calendar and books appointments. Sending email always waits for your OK, and he can't delete mail.</p>

      <h3 className="text-sm text-ink mb-2">Easiest: sign in to Google on your Mac (no keys or codes)</h3>
      <ol className="text-sm text-dim list-decimal pl-5 space-y-1 mb-3">
        <li>Click <b>Open Internet Accounts</b> → <b>Add Account</b> → <b>Google</b> and sign in like normal.</li>
        <li>Make sure <b>Mail</b> and <b>Calendars</b> are switched on for that account.</li>
        <li>Click <b>Use my Mac's Gmail &amp; Calendar</b>, then <b>Test</b>. If macOS asks whether JARVIS may control Mail or Calendar, click <b>OK</b>.</li>
      </ol>
      <div className="flex flex-wrap gap-2 mb-2">
        <Button onClick={() => api.openInternetAccounts().catch(e => setMsg({ text: (e as Error).message, bad: true }))}>Open Internet Accounts</Button>
        {st.mac
          ? <Button tone="danger" onClick={async () => setG(await api.useMacAccounts(false))}>Stop using the Mac's accounts</Button>
          : <Button tone="primary" onClick={async () => { setG(await api.useMacAccounts(true)); runTest() }}>Use my Mac's Gmail &amp; Calendar</Button>}
        {st.provider && <Button onClick={runTest}>Test</Button>}
      </div>
      {test && <p className={`text-sm mb-2 ${test.startsWith('Working') ? 'text-ok' : test.startsWith('Checking') ? 'text-dim' : 'text-amber'}`} role="status">{test}</p>}

      <button className="text-sm text-arc hover:underline mt-4 mb-3" onClick={() => setAdvanced(!advanced)} aria-expanded={advanced}>{advanced ? 'Hide' : 'Show'} advanced: direct Google connection (own client ID)</button>
      {advanced && <>
      <button className="text-sm text-arc hover:underline mb-3 block" onClick={() => setShowHow(!showHow)} aria-expanded={showHow}>{showHow ? 'Hide the steps' : 'How to get a Google client ID (5 minutes, once)'}</button>
      {showHow && (
        <ol className="text-sm text-dim list-decimal pl-5 space-y-1.5 mb-4">
          <li>Open <b>console.cloud.google.com</b>, create a project (any name, e.g. “JARVIS”).</li>
          <li><b>APIs &amp; Services → Library</b>: enable <b>Gmail API</b> and <b>Google Calendar API</b>.</li>
          <li><b>OAuth consent screen</b>: External, app name “JARVIS”, your email; add yourself as a test user. Then click <b>Publish app</b>.</li>
          <li><b>Credentials → Create credentials → OAuth client ID → Desktop app</b>. Copy the <b>Client ID</b> and <b>Client secret</b> here.</li>
          <li>Click <b>Save</b>, then <b>Connect Google</b> and allow access.</li>
        </ol>
      )}
      <div className="grid md:grid-cols-2 gap-4">
        <Field label="Client ID"><input className={inputCls} placeholder="….apps.googleusercontent.com" value={set.client_id} onChange={e => upd({ client_id: e.target.value.trim() })} /></Field>
        <Field label="Client secret" hint={st.client_configured ? 'Saved in Keychain. Paste to replace.' : undefined}>
          <input className={inputCls} type="password" autoComplete="off" placeholder={st.client_configured ? '••••••••' : 'GOCSPX-…'} value={secret} onChange={e => setSecret(e.target.value)} /></Field>
      </div>
      </>}
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
        {(advanced || st.client_configured) && <Button disabled={!st.client_configured && !(set.client_id && secret)} onClick={async () => { await saveAll(); location.href = '/api/google/connect' }}>{st.provider === 'google' ? 'Reconnect Google' : 'Connect Google directly'}</Button>}
        {st.provider === 'google' && <Button tone="danger" onClick={async () => setG(await api.disconnectGoogle())}>Disconnect</Button>}
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

function RemoteSection() {
  const [r, setR] = useState<Awaited<ReturnType<typeof api.remote>> | null>(null)
  const [code, setCode] = useState('')
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => api.remote().then(setR).catch(() => {})
  useEffect(() => { load() }, [])
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setMsg(null)
    try { await fn(); setMsg({ text: ok }); load() } catch (e) { setMsg({ text: (e as Error).message, bad: true }) } finally { setBusy(false) }
  }
  if (!r) return null
  const on = r.serving && r.url
  return (
    <Section title="JARVIS on your phone">
      <p className="text-sm text-dim mb-3">Open the Command Center and chat with JARVIS from your iPhone, anywhere, while this Mac is on. It goes through <b>Tailscale</b> (free), a private network between your own devices, so it's never on the public internet, and it also needs your passcode.</p>
      <ol className="text-sm text-dim list-decimal pl-5 space-y-1 mb-4">
        <li className={r.installed ? 'text-ok' : ''}>Install <b>Tailscale</b> on this Mac (tailscale.com/download or the Mac App Store) and sign in. {r.installed && '✓'}</li>
        <li className={r.running ? 'text-ok' : ''}>Install Tailscale on your iPhone (App Store) and sign in with the <b>same account</b>. {r.running && '✓ Mac connected'}</li>
        <li className={r.passcode ? 'text-ok' : ''}>Choose a passcode below. {r.passcode && '✓'}</li>
        <li className={on ? 'text-ok' : ''}>Click <b>Turn on phone access</b>. JARVIS texts you the link. On your iPhone open it in Safari → Share → <b>Add to Home Screen</b>.</li>
      </ol>
      <div className="flex flex-wrap gap-2 items-end">
        <Field label={r.passcode ? 'Change passcode' : 'Passcode (6+ characters)'}>
          <input type="password" autoComplete="new-password" className={inputCls} value={code} onChange={e => setCode(e.target.value)} />
        </Field>
        <Button disabled={busy || code.length < 6} onClick={() => run(async () => { await api.remotePasscode(code); setCode('') }, 'Passcode saved')}>Save passcode</Button>
      </div>
      <div className="flex flex-wrap gap-2 mt-4">
        {on
          ? <Button tone="danger" disabled={busy} onClick={() => run(api.remoteDisable, 'Phone access turned off')}>Turn off phone access</Button>
          : <Button tone="primary" disabled={busy || !r.installed || !r.passcode} onClick={() => run(api.remoteEnable, 'Phone access is on')}>Turn on phone access</Button>}
      </div>
      {on && <p className="text-sm mt-3">Your link: <a className="text-arc underline" href={r.url!} target="_blank" rel="noreferrer">{r.url}</a></p>}
      {r.error && <p className="text-amber text-sm mt-2">{r.error}</p>}
      {msg && <p className={`text-sm mt-3 ${msg.bad ? 'text-fault' : 'text-ok'}`} role="status">{msg.text}</p>}
    </Section>
  )
}

function BackupSection() {
  const [b, setB] = useState<Awaited<ReturnType<typeof api.backups>> | null>(null)
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => api.backups().then(setB).catch(() => {})
  useEffect(() => { load() }, [])
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setMsg(null)
    try { await fn(); setMsg({ text: ok }); load() } catch (e) { setMsg({ text: (e as Error).message, bad: true }) } finally { setBusy(false) }
  }
  return (
    <Section title="Backups">
      <p className="text-sm text-dim mb-3">Every day JARVIS saves his memory, chats, tasks, reminders and settings (kept for 14 days){b?.icloud ? ', with a copy in iCloud Drive → JARVIS Backups' : ''}. Your keys stay in the Keychain and are never in a backup.</p>
      <p className="text-[13px] text-faint mb-3">Last backup: {b?.last ? new Date(b.last).toLocaleString() : 'not yet'}</p>
      <Button disabled={busy} onClick={() => run(api.backupNow, 'Backup made')}>{busy ? 'Working…' : 'Back up now'}</Button>
      {!!b?.backups.length && (
        <ul className="mt-4 divide-y divide-seam/60 text-sm">
          {b.backups.slice(0, 7).map(x => (
            <li key={x.file} className="py-2 flex items-center gap-3">
              <span className="flex-1">{new Date(x.made).toLocaleString()} <span className="text-faint">· {Math.max(1, Math.round(x.size / 1024))} KB</span></span>
              <Button size="sm" disabled={busy} onClick={() => { if (confirm('Restore this backup? Current memory, chats and settings are replaced (a safety backup is made first).')) run(() => api.restoreBackup(x.file), 'Restored — reload the page') }}>Restore</Button>
            </li>
          ))}
        </ul>
      )}
      {msg && <p className={`text-sm mt-3 ${msg.bad ? 'text-fault' : 'text-ok'}`} role="status">{msg.text}</p>}
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
      <label className="flex items-center gap-3 text-sm mt-4">
        <input type="checkbox" className="accent-[#3CE7FF] size-4" checked={u?.auto ?? true}
          onChange={async e => { const auto = e.target.checked; await api.saveSettings({ update: { auto } }); setU(u ? { ...u, auto } : u) }} />
        Install updates automatically (when JARVIS isn't busy — never during a call or conversation)
      </label>
      <p className="text-[13px] text-faint mt-3">Updates keep your settings, chats, memory and keys. JARVIS checks for new versions every couple of hours.</p>
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
