import { useState } from 'react'
import { api } from '../api'
import type { AgentTool, Approval, Status } from '../api'
import { timeAgo, usePoll } from '../hooks'
import { Button, Dot, Empty, PageHead, Pill, inputCls, statusTone } from '../ui'

export default function Computer({ status }: { status: Status | null }) {
  const tools = usePoll(api.agentTools, 10000)
  const history = usePoll<Approval[]>(() => api.approvals('all'), 4000)
  const [picked, setPicked] = useState<AgentTool | null>(null)
  const a = status?.agent
  const perms = tools.data?.permissions
  const groups = (tools.data?.tools || []).reduce<Record<string, AgentTool[]>>((acc, t) => { (acc[t.category] ||= []).push(t); return acc }, {})

  return (
    <div className="px-8 py-8 max-w-[1100px] mx-auto">
      <PageHead title="Computer control" sub="Everything JARVIS can do on this Mac, what needs your approval, and what it has done. Edit the allowlists in Settings." />

      <section className="panel p-5 mb-6 flex flex-wrap items-center gap-x-8 gap-y-3">
        <div className="flex items-center gap-3">
          <Dot tone={!a?.online ? 'bad' : a.stopped ? 'warn' : 'ok'} />
          <div>
            <p className="font-display text-lg">This Mac</p>
            <p className="text-dim text-sm">{a?.online ? `Agent v${a.version} on ${a.platform}, up ${Math.round((a.uptime_s || 0) / 60)} min` : a?.error || 'Agent offline'}</p>
          </div>
        </div>
        {a?.online && <p className="text-sm text-dim">{a.executed} {a.executed === 1 ? 'action' : 'actions'} run · {a.failed} refused or failed{a.stopped ? ' · halted by emergency stop' : ''}</p>}
        {!a?.online && <code className="text-arc text-sm">./scripts/agent.sh start</code>}
      </section>

      <div className="grid lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-6 mb-8">
        <section className="panel p-5 min-w-0">
          <h2 className="font-display text-lg mb-3">Capabilities</h2>
          {Object.keys(groups).length === 0 && <Empty>Start the Mac agent to see its tools.</Empty>}
          <div className="mb-4">
            <h3 className="text-faint text-[13px] mb-1.5">Web browser (Playwright MCP)</h3>
            <div className="flex items-center gap-2 px-2 py-1.5">
              <span className="font-display text-[14px] w-36 shrink-0">25 browser tools</span>
              <span className="text-dim text-[13px] flex-1 min-w-0">Read pages freely; buying, sending, forms, uploads and unapproved sites ask first.</span>
              <Pill tone={status?.browser.available ? 'amber' : 'dim'}>{status?.browser.available ? 'some ask' : 'not installed'}</Pill>
            </div>
          </div>
          {Object.entries(groups).map(([cat, ts]) => (
            <div key={cat} className="mb-4 last:mb-0">
              <h3 className="text-faint text-[13px] mb-1.5 capitalize">{cat}</h3>
              <ul className="space-y-1">
                {ts.map(t => (
                  <li key={t.name}>
                    <button onClick={() => setPicked(t)} className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-lg ${picked?.name === t.name ? 'bg-plate' : 'hover:bg-graphite'}`}>
                      <span className="font-display text-[14px] w-36 shrink-0 truncate">{t.name}</span>
                      <span className="text-dim text-[13px] truncate flex-1 min-w-0">{t.description}</span>
                      {!t.enabled ? <Pill>disabled</Pill> : t.requires_approval ? <Pill tone="amber">asks first</Pill> : <Pill tone="ok">automatic</Pill>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
        <section className="panel p-5">
          {picked ? <RunTool key={picked.name} tool={picked} /> : (
            <>
              <h2 className="font-display text-lg mb-3">Approved scope</h2>
              <Scope label="Applications" items={perms?.approved_apps} />
              <Scope label="Websites" items={perms?.approved_domains} />
              <Scope label="Folders" items={perms?.approved_directories} />
              <p className="text-[13px] text-faint mt-4">Select a capability to run it yourself.</p>
            </>
          )}
        </section>
      </div>

      <h2 className="font-display text-lg mb-3">Approval history</h2>
      <ul className="panel divide-y divide-seam/70">
        {(history.data || []).slice(0, 30).map(ap => (
          <li key={ap.id} className="p-4 flex flex-wrap items-start gap-3">
            <Pill tone={statusTone(ap.status)}>{ap.status}</Pill>
            <div className="flex-1 min-w-[240px]">
              <p className="font-display text-[14px]">{ap.summary}</p>
              {ap.result && <p className="text-[12px] text-dim truncate">{ap.result}</p>}
            </div>
            <span className="text-faint text-[13px]">{timeAgo(ap.created_at)}</span>
          </li>
        ))}
        {history.data?.length === 0 && <li><Empty>Nothing has needed approval yet.</Empty></li>}
      </ul>
    </div>
  )
}

function Scope({ label, items }: { label: string; items?: string[] }) {
  return (
    <div className="mb-3">
      <p className="text-faint text-[13px] mb-1">{label}</p>
      <div className="flex flex-wrap gap-1.5">{(items || []).map(i => <Pill key={i}>{i}</Pill>)}{!items?.length && <span className="text-dim text-sm">None approved</span>}</div>
    </div>
  )
}

function RunTool({ tool }: { tool: AgentTool }) {
  const props = tool.input_schema.properties || {}
  const [args, setArgs] = useState<Record<string, unknown>>({})
  const [out, setOut] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true); setOut(null)
    try { const r = await api.runTool(tool.name, args); setOut(r.status === 'ok' ? JSON.stringify(r.output, null, 2) : `Error: ${r.error}`) }
    catch (e) { setOut(`Error: ${(e as Error).message}`) }
    setBusy(false)
  }
  return (
    <div>
      <h2 className="font-display text-lg">{tool.name}</h2>
      <p className="text-dim text-sm mb-4">{tool.description}</p>
      <div className="space-y-2 mb-4">
        {Object.entries(props).map(([k, p]) => p.enum
          ? <select key={k} className={inputCls} value={String(args[k] ?? '')} onChange={e => setArgs({ ...args, [k]: e.target.value })} aria-label={k}>
              <option value="">{k}</option>{p.enum.map(v => <option key={v}>{v}</option>)}</select>
          : p.type === 'object' ? <textarea key={k} className={inputCls + ' h-20 py-2'} placeholder={`${k} (JSON)`} aria-label={k}
              onChange={e => { try { setArgs({ ...args, [k]: JSON.parse(e.target.value) }) } catch { /* keep typing */ } }} />
          : <input key={k} className={inputCls} placeholder={k + (tool.input_schema.required?.includes(k) ? '' : ' (optional)')} aria-label={k}
              onChange={e => setArgs({ ...args, [k]: p.type === 'integer' ? Number(e.target.value) : e.target.value })} />)}
      </div>
      <p className="text-[13px] text-dim mb-2">This will run exactly:</p>
      <pre className="text-[12.5px] bg-black border border-seam rounded-lg p-3 mb-3 whitespace-pre-wrap">{tool.name}({JSON.stringify(args)})</pre>
      <Button tone={tool.requires_approval ? 'amber' : 'primary'} disabled={busy || !tool.enabled} onClick={run}>
        {busy ? 'Running…' : tool.requires_approval ? 'Approve and run' : 'Run'}
      </Button>
      {out && <pre className="mt-3 text-[12px] bg-black border border-seam rounded-lg p-3 max-h-72 overflow-auto whitespace-pre-wrap">{out}</pre>}
    </div>
  )
}
