import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

/** Shows what went wrong instead of a black screen, with a way back. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }
  static getDerivedStateFromError(error: Error) { return { error } }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('JARVIS screen crashed:', error, info.componentStack) }
  componentDidUpdate(prev: { resetKey?: string }) { if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null }) }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="p-8 max-w-xl">
        <h2 className="font-display text-xl text-fault mb-2">This screen hit a problem</h2>
        <p className="text-dim text-sm mb-3">The rest of JARVIS still works. This usually means the app and its background part are on different versions — updating fixes it.</p>
        <pre className="bg-black border border-seam rounded-lg p-3 text-[12px] text-amber whitespace-pre-wrap mb-4">{this.state.error.message}</pre>
        <div className="flex gap-2">
          <button className="h-10 px-4 rounded-lg bg-arc text-black text-sm" onClick={() => location.reload()}>Reload</button>
          <button className="h-10 px-4 rounded-lg border border-seam text-sm" onClick={() => fetch('/api/update/apply', { method: 'POST' }).then(() => alert('Updating — JARVIS will restart in a minute or two.'))}>Update JARVIS now</button>
        </div>
      </div>
    )
  }
}
