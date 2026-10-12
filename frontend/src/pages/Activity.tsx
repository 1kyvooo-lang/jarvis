import { useState } from 'react'
import { api } from '../api'
import type { Activity } from '../api'
import { usePoll } from '../hooks'
import { Empty, PageHead, Pill, statusTone } from '../ui'

const FILTERS = ['all', 'ok', 'error', 'pending', 'denied', 'info']

export default function ActivityPage() {
  const { data } = usePoll<Activity[]>(() => api.activity(500), 4000)
  const [f, setF] = useState('all')
  const rows = (data || []).filter(r => f === 'all' || r.status === f)
  return (
    <div className="px-8 py-8 max-w-[1240px] mx-auto">
      <PageHead title="Activity log" sub="Every tool request, approval and error, newest first. Secrets are redacted before anything is logged." />
      <div className="flex gap-2 mb-4">
        {FILTERS.map(x => (
          <button key={x} onClick={() => setF(x)} aria-pressed={f === x}
            className={`h-8 px-3 rounded-full text-sm border capitalize ${f === x ? 'border-arc/60 text-arc' : 'border-seam text-dim hover:text-ink'}`}>{x}</button>
        ))}
      </div>
      <div className="panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-faint">
            <tr className="border-b border-seam">
              <th className="font-normal p-3 w-40">Time</th><th className="font-normal p-3">Action</th><th className="font-normal p-3">Tool</th>
              <th className="font-normal p-3">Approval</th><th className="font-normal p-3">Result</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} className="border-b border-seam/50 align-top">
                <td className="p-3 text-dim whitespace-nowrap">{new Date(r.ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })}</td>
                <td className="p-3 max-w-[360px]">{r.action}</td>
                <td className="p-3 font-display whitespace-nowrap">{r.tool ?? '—'}</td>
                <td className="p-3 text-dim whitespace-nowrap">{r.approval ?? '—'}</td>
                <td className="p-3 max-w-[340px]">
                  <Pill tone={statusTone(r.status)}>{r.status}</Pill>
                  {r.error && <p className="text-fault text-[13px] mt-1">{r.error}</p>}
                  {r.result && !r.error && <details className="mt-1"><summary className="text-[13px] text-dim cursor-pointer">Output</summary>
                    <pre className="text-[12px] text-dim whitespace-pre-wrap break-all mt-1">{r.result}</pre></details>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <Empty>No entries{f !== 'all' ? ` with status “${f}”` : ''}.</Empty>}
      </div>
    </div>
  )
}
