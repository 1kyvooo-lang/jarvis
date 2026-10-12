import { useState } from 'react'
import { api } from '../api'
import type { Approval } from '../api'
import { timeAgo, usePoll } from '../hooks'
import { Button } from '../ui'

/** Pending approvals, shown at the top of every page so nothing waits unseen. */
export function ApprovalTray({ onChange }: { onChange: () => void }) {
  const { data, refresh } = usePoll<Approval[]>(() => api.approvals('pending'), 2500)
  const [busy, setBusy] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)
  if (!data?.length) return null

  const decide = async (id: number, d: 'approve' | 'deny') => {
    setBusy(id); setErr(null)
    try { await api.decide(id, d) } catch (e) { setErr((e as Error).message) }
    setBusy(null); refresh(); onChange()
  }
  return (
    <section aria-label="Actions waiting for approval" className="border-b border-amber/40 bg-amber/[0.06] px-6 py-3 space-y-2">
      {data.map(a => (
        <div key={a.id} className="flex flex-wrap items-center gap-3">
          <span className="size-2 rounded-full bg-amber shadow-[0_0_10px_#FFB547]" aria-hidden />
          <div className="flex-1 min-w-[260px]">
            <p className="text-sm text-ink">JARVIS wants to run <b className="font-display text-amber">{a.tool.replace(/^browser_/, 'browser · ')}</b>
              {a.reason && a.reason !== 'needs your approval' && <span className="text-dim"> — {a.reason}</span>} <span className="text-faint">· {timeAgo(a.created_at)}</span></p>
            <code className="block text-[12.5px] text-dim break-all">{JSON.stringify(a.args)}</code>
          </div>
          <Button size="sm" tone="amber" disabled={busy === a.id} onClick={() => decide(a.id, 'approve')}>Approve</Button>
          <Button size="sm" disabled={busy === a.id} onClick={() => decide(a.id, 'deny')}>Deny</Button>
        </div>
      ))}
      {err && <p className="text-fault text-sm">{err}</p>}
    </section>
  )
}
