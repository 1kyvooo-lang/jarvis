import { useState } from 'react'
import { api } from '../api'
import type { AgentTool, Step, Task } from '../api'
import { timeAgo, usePoll } from '../hooks'
import { Button, Empty, Field, PageHead, Pill, inputCls, statusTone } from '../ui'

export default function Tasks() {
  const tasks = usePoll<Task[]>(api.tasks, 3000)
  const tools = usePoll(api.agentTools, 0)
  const [mode, setMode] = useState<'todo' | 'automation'>('todo')
  const [title, setTitle] = useState('')
  const [desc, setDesc] = useState('')
  const [due, setDue] = useState('')
  const [steps, setSteps] = useState<Step[]>([{ tool: 'get_datetime', args: {} }])
  const [err, setErr] = useState<string | null>(null)
  const [edit, setEdit] = useState<Task | null>(null)

  const create = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null)
    try {
      await api.addTask({ title, description: desc, due_at: due ? new Date(due).toISOString() : null, steps: mode === 'automation' ? steps : null })
      setTitle(''); setDesc(''); setDue(''); tasks.refresh()
    } catch (e) { setErr((e as Error).message) }
  }
  const act = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn() } catch (e) { setErr((e as Error).message) } tasks.refresh() }

  const all = tasks.data || []
  const proposed = all.filter(t => t.status === 'proposed')
  const todos = all.filter(t => !t.steps && t.status !== 'proposed')
  const autos = all.filter(t => t.steps && t.status !== 'proposed')

  return (
    <div className="px-8 py-8 max-w-[1100px] mx-auto">
      <PageHead title="Tasks and automations" sub="To-dos are reminders. Automations run Mac agent actions in order, on a schedule if you set one. Automations JARVIS proposes never run until you approve them." />

      {proposed.length > 0 && (
        <section className="mb-8 border border-amber/40 rounded-[14px] p-5 bg-amber/[0.04]">
          <h2 className="font-display text-lg text-amber mb-3">Proposed by JARVIS</h2>
          {proposed.map(t => (
            <div key={t.id} className="py-3 border-t border-amber/20 first:border-0">
              <div className="flex flex-wrap items-center gap-3">
                <p className="flex-1 font-medium">{t.title}</p>
                <Button size="sm" tone="amber" onClick={() => act(() => api.approveTask(t.id))}>Approve and queue</Button>
                <Button size="sm" onClick={() => act(() => api.cancelTask(t.id))}>Decline</Button>
              </div>
              {t.description && <p className="text-dim text-sm mt-1">{t.description}</p>}
              <StepList steps={t.steps || []} />
              {t.due_at && <p className="text-[13px] text-dim mt-1">Runs at {new Date(t.due_at).toLocaleString()}</p>}
            </div>
          ))}
        </section>
      )}

      <form onSubmit={create} className="panel p-5 mb-8 space-y-4">
        <div className="flex gap-2" role="tablist">
          {(['todo', 'automation'] as const).map(m => (
            <button type="button" key={m} role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
              className={`h-8 px-3 rounded-full text-sm border ${mode === m ? 'border-arc/60 text-arc' : 'border-seam text-dim'}`}>
              {m === 'todo' ? 'To-do' : 'Automation'}
            </button>
          ))}
        </div>
        <div className="grid md:grid-cols-[2fr_1fr] gap-4">
          <Field label="Title"><input className={inputCls} value={title} onChange={e => setTitle(e.target.value)} required /></Field>
          <Field label={mode === 'automation' ? 'Run at (optional)' : 'Due (optional)'}>
            <input type="datetime-local" className={inputCls} value={due} onChange={e => setDue(e.target.value)} />
          </Field>
        </div>
        <Field label="Notes"><input className={inputCls} value={desc} onChange={e => setDesc(e.target.value)} /></Field>
        {mode === 'automation' && <StepEditor steps={steps} setSteps={setSteps} tools={tools.data?.tools || []} />}
        {err && <p className="text-fault text-sm" role="alert">{err}</p>}
        <Button tone="primary" disabled={!title.trim()}>{mode === 'todo' ? 'Add to-do' : 'Create automation'}</Button>
      </form>

      <div className="grid lg:grid-cols-2 gap-6">
        <section className="panel p-5">
          <h2 className="font-display text-lg mb-3">To-dos</h2>
          {todos.length ? <ul className="divide-y divide-seam/70">{todos.map(t => (
            <li key={t.id} className="py-2.5 flex items-center gap-3">
              <input type="checkbox" className="accent-[#3CE7FF] size-4" checked={t.status === 'done'} aria-label={`Mark ${t.title} done`}
                onChange={() => act(() => api.editTask(t.id, { status: t.status === 'done' ? 'todo' : 'done' }))} />
              {edit?.id === t.id ? (
                <>
                  <input className={inputCls + ' h-8 flex-1'} value={edit.title} onChange={e => setEdit({ ...edit, title: e.target.value })} autoFocus />
                  <Button size="sm" tone="primary" onClick={() => act(async () => { await api.editTask(t.id, { title: edit.title }); setEdit(null) })}>Save</Button>
                </>
              ) : (
                <>
                  <button className={`flex-1 text-left truncate ${t.status === 'done' || t.status === 'cancelled' ? 'line-through text-faint' : ''}`} onClick={() => setEdit(t)} title="Click to rename">{t.title}</button>
                  {t.due_at && <span className="text-[13px] text-faint">{new Date(t.due_at).toLocaleDateString()}</span>}
                  {t.source === 'assistant' && <Pill>by JARVIS</Pill>}
                  <button className="text-faint hover:text-fault text-sm" onClick={() => act(() => api.deleteTask(t.id))} aria-label={`Delete ${t.title}`}>Delete</button>
                </>
              )}
            </li>))}</ul> : <Empty>No to-dos.</Empty>}
        </section>

        <section className="panel p-5">
          <h2 className="font-display text-lg mb-3">Automations</h2>
          {autos.length ? <ul className="divide-y divide-seam/70">{autos.map(t => (
            <li key={t.id} className="py-3">
              <div className="flex items-center gap-3">
                <span className="flex-1 truncate">{t.title}</span>
                <Pill tone={statusTone(t.status)}>{t.status}</Pill>
                {['queued', 'todo'].includes(t.status) && <Button size="sm" onClick={() => act(() => api.cancelTask(t.id))}>Cancel</Button>}
                {['completed', 'failed', 'cancelled'].includes(t.status) && t.approved === 1 && <Button size="sm" onClick={() => act(() => api.rerunTask(t.id))}>Run again</Button>}
              </div>
              <StepList steps={t.steps || []} />
              <p className="text-[12px] text-faint mt-1">{t.due_at && t.status === 'queued' ? `Scheduled ${new Date(t.due_at).toLocaleString()}` : `Updated ${timeAgo(t.updated_at)}`}</p>
              {t.result && <details className="mt-1"><summary className="text-[13px] text-dim cursor-pointer">Result</summary>
                <pre className="text-[12px] bg-black border border-seam rounded-lg p-2 mt-1 max-h-48 overflow-auto whitespace-pre-wrap">{pretty(t.result)}</pre></details>}
            </li>))}</ul> : <Empty>No automations yet. Create one above, or ask JARVIS to propose one.</Empty>}
        </section>
      </div>
    </div>
  )
}

function pretty(s: string) { try { return JSON.stringify(JSON.parse(s), null, 2) } catch { return s } }

function StepList({ steps }: { steps: Step[] }) {
  return (
    <ol className="mt-2 space-y-1 text-sm list-decimal pl-5 marker:text-faint">
      {steps.map((s, i) => <li key={i}><span className="font-display">{s.tool}</span> <span className="text-dim">{Object.keys(s.args || {}).length ? JSON.stringify(s.args) : ''}</span></li>)}
    </ol>
  )
}

function StepEditor({ steps, setSteps, tools }: { steps: Step[]; setSteps: (s: Step[]) => void; tools: AgentTool[] }) {
  const upd = (i: number, s: Step) => setSteps(steps.map((x, j) => (j === i ? s : x)))
  return (
    <div className="space-y-3">
      <p className="text-sm">Steps run in order; the automation stops at the first failure.</p>
      {steps.map((s, i) => {
        const def = tools.find(t => t.name === s.tool)
        const props = def?.input_schema.properties || {}
        return (
          <div key={i} className="flex flex-wrap items-center gap-2 bg-black/40 border border-seam rounded-lg p-3">
            <span className="text-faint text-sm w-5">{i + 1}.</span>
            <select className={inputCls + ' w-48 h-9'} value={s.tool} onChange={e => upd(i, { tool: e.target.value, args: {} })} aria-label={`Step ${i + 1} tool`}>
              {tools.filter(t => t.enabled).map(t => <option key={t.name} value={t.name}>{t.name}</option>)}
            </select>
            {Object.entries(props).filter(([, p]) => p.type === 'string' || p.type === 'integer').map(([k, p]) => (
              p.enum
                ? <select key={k} className={inputCls + ' w-36 h-9'} value={String(s.args[k] ?? '')} onChange={e => upd(i, { ...s, args: { ...s.args, [k]: e.target.value } })} aria-label={k}>
                    <option value="">{k}</option>{p.enum.map(v => <option key={v}>{v}</option>)}</select>
                : <input key={k} className={inputCls + ' flex-1 min-w-[140px] h-9'} placeholder={k} value={String(s.args[k] ?? '')}
                    onChange={e => upd(i, { ...s, args: { ...s.args, [k]: p.type === 'integer' ? Number(e.target.value) : e.target.value } })} aria-label={k} />
            ))}
            {steps.length > 1 && <button type="button" className="text-faint hover:text-fault text-sm ml-auto" onClick={() => setSteps(steps.filter((_, j) => j !== i))}>Remove</button>}
          </div>
        )
      })}
      <Button type="button" size="sm" onClick={() => setSteps([...steps, { tool: tools[0]?.name || 'get_datetime', args: {} }])}>Add step</Button>
      {tools.length === 0 && <p className="text-amber text-sm">The Mac agent is offline, so its tool list isn’t available.</p>}
    </div>
  )
}
