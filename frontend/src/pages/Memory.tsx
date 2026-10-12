import { useState } from 'react'
import { api } from '../api'
import type { Conversation, Memory } from '../api'
import { timeAgo, usePoll } from '../hooks'
import { Button, Empty, PageHead, Pill, inputCls } from '../ui'

const KINDS = [
  { id: '', label: 'Everything' },
  { id: 'preference', label: 'Preferences' },
  { id: 'fact', label: 'Facts' },
  { id: 'project', label: 'Projects' },
  { id: 'goal', label: 'Goals' },
  { id: 'instruction', label: 'Instructions' },
]

export default function MemoryPage() {
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('')
  const list = usePoll<Memory[]>(() => api.memories(q, kind), 0, [q, kind])
  const convs = usePoll<Conversation[]>(() => api.conversations(), 0)
  const [draft, setDraft] = useState({ kind: 'fact', content: '' })
  const [err, setErr] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ id: number; kind: string; content: string } | null>(null)

  const add = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(null)
    try { await api.addMemory(draft.kind, draft.content); setDraft({ ...draft, content: '' }); list.refresh() }
    catch (e) { setErr((e as Error).message) }
  }
  const save = async () => {
    if (!editing) return
    try { await api.editMemory(editing.id, { kind: editing.kind, content: editing.content }); setEditing(null); list.refresh() }
    catch (e) { setErr((e as Error).message) }
  }

  return (
    <div className="px-8 py-8 max-w-[1100px] mx-auto">
      <PageHead title="Memory" sub="What JARVIS knows about you. Only relevant items are sent to Claude with each message. Secrets are refused automatically.">
        <a href="/api/memories/export" download><Button>Export JSON</Button></a>
      </PageHead>

      <form onSubmit={add} className="panel p-4 flex flex-wrap gap-3 mb-6">
        <select className={inputCls + ' w-40'} value={draft.kind} onChange={e => setDraft({ ...draft, kind: e.target.value })} aria-label="Kind">
          {KINDS.slice(1).map(k => <option key={k.id} value={k.id}>{k.label.replace(/s$/, '')}</option>)}
        </select>
        <input className={inputCls + ' flex-1 min-w-[240px]'} placeholder="e.g. I deploy backends to Render" value={draft.content}
          onChange={e => setDraft({ ...draft, content: e.target.value })} aria-label="New memory" />
        <Button tone="primary" disabled={!draft.content.trim()}>Save memory</Button>
        {err && <p className="w-full text-fault text-sm" role="alert">{err}</p>}
      </form>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        {KINDS.map(k => (
          <button key={k.id} onClick={() => setKind(k.id)} aria-pressed={kind === k.id}
            className={`h-8 px-3 rounded-full text-sm border ${kind === k.id ? 'border-arc/60 text-arc' : 'border-seam text-dim hover:text-ink'}`}>{k.label}</button>
        ))}
        <input className={inputCls + ' h-8 text-sm w-56 ml-auto'} placeholder="Search memory" value={q} onChange={e => setQ(e.target.value)} aria-label="Search memory" />
      </div>

      <ul className="panel divide-y divide-seam/70 mb-10">
        {(list.data || []).map(m => (
          <li key={m.id} className="p-4 flex gap-4 items-start">
            {editing?.id === m.id ? (
              <div className="flex-1 flex flex-wrap gap-2">
                <select className={inputCls + ' w-36'} value={editing.kind} onChange={e => setEditing({ ...editing, kind: e.target.value })}>
                  {KINDS.slice(1).map(k => <option key={k.id} value={k.id}>{k.id}</option>)}
                </select>
                <input className={inputCls + ' flex-1 min-w-[200px]'} value={editing.content} onChange={e => setEditing({ ...editing, content: e.target.value })} autoFocus />
                <Button size="sm" tone="primary" onClick={save}>Save</Button>
                <Button size="sm" onClick={() => setEditing(null)}>Cancel</Button>
              </div>
            ) : (
              <>
                <Pill tone={m.kind === 'instruction' ? 'arc' : 'dim'}>{m.kind}</Pill>
                <div className="flex-1 min-w-0">
                  <p>{m.content}</p>
                  <p className="text-[12px] text-faint mt-0.5">{m.source === 'assistant' ? 'Saved by JARVIS' : 'Added by you'} · {timeAgo(m.updated_at)}</p>
                </div>
                <Button size="sm" onClick={() => setEditing({ id: m.id, kind: m.kind, content: m.content })}>Edit</Button>
                <Button size="sm" tone="danger" onClick={async () => { await api.deleteMemory(m.id); list.refresh() }}>Delete</Button>
              </>
            )}
          </li>
        ))}
        {list.data?.length === 0 && <li><Empty>{q || kind ? 'No matching memories.' : 'Nothing saved yet. Add something above, or tell JARVIS “remember that…”.'}</Empty></li>}
      </ul>

      <h2 className="font-display text-lg mb-3">Conversation history</h2>
      <p className="text-dim text-sm mb-3">{convs.data?.length ?? 0} conversations stored locally. Open, search and delete them from the Assistant page.</p>
    </div>
  )
}
