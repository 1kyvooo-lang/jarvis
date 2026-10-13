// Thin client for the JARVIS backend. All calls go to /api on the same origin.

export type Status = {
  brain: { ready: boolean; state: string; detail: string; model: string | null; installed: boolean; model_configured: boolean | null; restarts?: number }
  agent: { online: boolean; error?: string; service?: { state: string; detail: string; restarts: number }; version?: string; platform?: string; stopped?: boolean; uptime_s?: number; executed?: number; failed?: number; tool_count?: number }
  voice: { elevenlabs: boolean; key_source: string; key_hint: string | null; provider: string }
  browser: { available: boolean }
  phone: PhoneStatus
  update?: { available: boolean }
  google?: { client_configured: boolean; connected: boolean; email: string | null }
  emergency_stop: boolean
  user_name: string
  platform: string
  counts: { pending_approvals: number; open_tasks: number; memories: number; conversations: number }
}
export type ToolCall = { id: string; name: string; input: Record<string, unknown>; result?: string; is_error?: boolean; status?: string; approval_id?: number; output?: unknown; error?: string }
export type Part = { type: 'text'; text: string } | { type: 'tool'; id: string }
export type Message = { id: number | string; role: 'user' | 'assistant' | 'event'; text: string; tools?: ToolCall[]; parts?: Part[]; created_at: string; streaming?: boolean; error?: string | null }
export type Conversation = { id: string; title: string; created_at: string; updated_at: string }
export type Memory = { id: number; kind: string; content: string; source: string; created_at: string; updated_at: string }
export type Step = { tool: string; args: Record<string, unknown> }
export type Task = { id: number; title: string; description: string; status: string; due_at: string | null; steps: Step[] | null; result: string | null; source: string; approved: number; created_at: string; updated_at: string }
export type Approval = { id: number; conversation_id: string | null; tool: string; args: Record<string, unknown>; summary: string; status: string; result: string | null; created_at: string; kind?: string; reason?: string | null }
export type Activity = { id: number; ts: string; action: string; tool: string | null; status: string; approval: string | null; result: string | null; error: string | null; source: string | null }
export type AgentTool = { name: string; description: string; input_schema: { properties?: Record<string, { type?: string; enum?: string[]; description?: string }>; required?: string[] }; category: string; sensitive: boolean; requires_approval: boolean; enabled: boolean; mac_only: boolean }
export type Permissions = { approved_apps: string[]; approved_domains: string[]; approved_directories: string[]; approval_required: string[]; disabled_tools: string[]; browser: BrowserPolicy; obsidian_vault?: string }
export type PhoneStatus = { enabled: boolean; configured: boolean; public_url: string | null; webhooks: string | null; error: string | null; token_hint: string | null }
export type UpdateInfo = { repo: string; current: string | null; running_version?: string | null; auto?: boolean; latest: { sha: string; message: string; date: string | null } | null; available: boolean; checked_at: number | null; error: string | null; running: boolean }
export type GoogleInfo = { status: { client_configured: boolean; connected: boolean; email: string | null; redirect_uri: string }
  settings: { client_id: string; email: string; business_hours: { days: number[]; start: string; end: string }; slot_minutes: number; min_notice_hours: number } }
export type Receptionist = { answer_others: boolean; business_name: string; about: string; booking: boolean; appointment_minutes: number
  inbox_assistant: boolean; inbox_minutes: number; allow_archive: boolean; approve_by_text: boolean; labels: string[] }
export type Reminder = { id: number; text: string; due_at: string; via: string; status: string }
export type PhoneSettings = { enabled: boolean; account_sid: string; twilio_number: string; owner_number: string; language: string }
export type Settings = {
  user_name: string; assistant_name: string; emergency_stop: boolean
  voice: { provider: 'elevenlabs' | 'browser'; auto_speak: boolean; voice_id: string; voice_name: string; tts_model: string; stt_language: string; browser_voice_name: string; rate: number }
  memory: { auto_retrieve: boolean; max_items: number }
  hermes: { api_key: string; binary: string }
  browser: { headless: boolean }
  receptionist: Receptionist
  briefing: { enabled: boolean; time: string; days: number[]; via: 'text' | 'call' | 'notification'; last_sent?: string; conversation?: string }
  router: { enabled: boolean; auto: boolean; routes: Record<string, { model?: string; provider?: string; base_url?: string }> }
  update?: { auto: boolean }
  wake: { enabled: boolean; threshold: number; greeting: string; open_at_login: boolean }
}
export type BrowserPolicy = { ask_outside_approved_domains: boolean; always_ask: string[]; risky_words: string[] }
export type ElevenVoice = { voice_id: string; name: string; category?: string; labels?: Record<string, string>; preview_url?: string }
export type Integration = { key: string; name: string; state: string; implemented: boolean; env_vars: string[]; note: string }

/** Defaults for every settings section, so the screens work even with an older JARVIS backend. */
export const SETTINGS_DEFAULTS = {
  user_name: '', assistant_name: 'JARVIS', emergency_stop: false,
  voice: { provider: 'elevenlabs', auto_speak: true, voice_id: '', voice_name: '', tts_model: '', stt_language: '', browser_voice_name: '', rate: 1 },
  memory: { auto_retrieve: true, max_items: 12 },
  hermes: { api_key: '', binary: '' },
  browser: { headless: false },
  receptionist: { answer_others: true, business_name: '', about: '', booking: true, appointment_minutes: 30, inbox_assistant: false,
    inbox_minutes: 10, allow_archive: false, approve_by_text: true, labels: ['Needs reply', 'Appointments', 'Important', 'Receipts', 'Newsletters', 'Other'] },
  briefing: { enabled: false, time: '08:00', days: [1, 2, 3, 4, 5, 6, 7], via: 'text' },
  router: { enabled: false, auto: true, routes: {} },
  wake: { enabled: true, threshold: 0.5, greeting: 'Yes? What do you need?', open_at_login: true },
} as const

function withDefaults(s: Partial<Settings> | undefined): Settings {
  const out: Record<string, unknown> = { ...SETTINGS_DEFAULTS, ...(s || {}) }
  for (const [k, v] of Object.entries(SETTINGS_DEFAULTS)) {
    if (v && typeof v === 'object' && !Array.isArray(v)) out[k] = { ...v, ...((s as Record<string, unknown> | undefined)?.[k] as object || {}) }
  }
  return out as unknown as Settings
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } })
  } catch {
    throw new ApiError('Backend not reachable. Is it running? Try ./scripts/dev.sh', 0)
  }
  if (!res.ok) {
    let detail = res.statusText
    try { const j = await res.json(); detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* ignore */ }
    throw new ApiError(detail, res.status)
  }
  return res.json() as Promise<T>
}

const body = (b: unknown) => ({ body: JSON.stringify(b) })

export const api = {
  status: () => req<Status>('/api/status'),
  setElevenLabsKey: (api_key: string) => req<{ ok: boolean; stored_in: string; voices: number }>('/api/setup/elevenlabs', { method: 'POST', ...body({ api_key }) }),
  deleteElevenLabsKey: () => req('/api/setup/elevenlabs', { method: 'DELETE' }),
  hermesSetup: () => req<{ ok: boolean }>('/api/hermes/setup', { method: 'POST' }),
  hermesRestart: () => req('/api/hermes/restart', { method: 'POST' }),
  restartServices: () => req('/api/services/restart', { method: 'POST' }),
  agentRestart: () => req('/api/agent/restart', { method: 'POST' }),
  shutdown: () => req('/api/shutdown', { method: 'POST' }),
  phone: () => req<{ settings: PhoneSettings; status: PhoneStatus; cloudflared: boolean }>('/api/phone'),
  savePhone: (p: PhoneSettings & { auth_token?: string }) => req<{ settings: PhoneSettings; status: PhoneStatus; cloudflared: boolean }>('/api/phone', { method: 'PUT', ...body(p) }),
  testCall: () => req('/api/phone/test-call', { method: 'POST' }),
  testSms: () => req('/api/phone/test-sms', { method: 'POST' }),
  system: () => req<{ cpu: number; ram: number; disk: number; battery: { percent: number; plugged: boolean } | null; network: boolean; uptime_h: number }>('/api/system'),
  google: () => req<GoogleInfo>('/api/google'),
  saveGoogle: (g: Partial<GoogleInfo['settings']> & { client_secret?: string }) => req<GoogleInfo>('/api/google', { method: 'PUT', ...body(g) }),
  disconnectGoogle: () => req<GoogleInfo>('/api/google', { method: 'DELETE' }),
  reminders: () => req<Reminder[]>('/api/reminders'),
  addReminder: (r: { text: string; at: string; via: string }) => req('/api/reminders', { method: 'POST', ...body(r) }),
  cancelReminder: (id: number) => req(`/api/reminders/${id}`, { method: 'DELETE' }),
  briefingNow: () => req<{ text: string; via: string }>('/api/briefing/now', { method: 'POST' }),
  backups: () => req<{ backups: { file: string; size: number; made: string }[]; icloud: string; last: string | null }>('/api/backups'),
  backupNow: () => req<{ file: string; icloud: string | null }>('/api/backups', { method: 'POST' }),
  restoreBackup: (file: string) => req(`/api/backups/${encodeURIComponent(file)}/restore`, { method: 'POST' }),
  remote: () => req<{ installed: boolean; running: boolean; url: string | null; serving: boolean; passcode: boolean; error: string | null }>('/api/remote'),
  remotePasscode: (passcode: string) => req('/api/remote/passcode', { method: 'POST', ...body({ passcode }) }),
  remoteEnable: () => req<{ url: string | null }>('/api/remote/enable', { method: 'POST' }),
  remoteDisable: () => req('/api/remote/disable', { method: 'POST' }),
  remoteLogin: (passcode: string) => req('/api/remote/login', { method: 'POST', ...body({ passcode }) }),
  update: () => req<UpdateInfo>('/api/update'),
  checkUpdate: () => req<UpdateInfo>('/api/update/check', { method: 'POST' }),
  applyUpdate: () => req<UpdateInfo>('/api/update/apply', { method: 'POST' }),
  voices: () => req<{ voices: ElevenVoice[] }>('/api/voice/voices'),
  voiceModels: () => req<{ models: { model_id: string; name: string }[] }>('/api/voice/models'),
  settings: () => req<{ settings: Settings; integrations: Integration[] }>('/api/settings').then(r => ({ ...r, settings: withDefaults(r.settings), integrations: r.integrations || [] })),
  saveSettings: (s: Partial<Settings>) => req<{ settings: Settings }>('/api/settings', { method: 'PUT', ...body(s) }).then(r => ({ settings: withDefaults(r.settings) })),
  permissions: () => req<Permissions>('/api/permissions'),
  savePermissions: (p: Permissions) => req<Permissions>('/api/permissions', { method: 'PUT', ...body(p) }),
  emergencyStop: () => req('/api/emergency-stop', { method: 'POST' }),
  resume: () => req('/api/resume', { method: 'POST' }),

  conversations: (q = '') => req<Conversation[]>(`/api/conversations${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  conversation: (id: string) => req<Conversation & { messages: Message[] }>(`/api/conversations/${id}`),
  renameConversation: (id: string, title: string) => req(`/api/conversations/${id}`, { method: 'PATCH', ...body({ title }) }),
  deleteConversation: (id: string) => req(`/api/conversations/${id}`, { method: 'DELETE' }),
  stopChat: (conversation_id: string) => req('/api/chat/stop', { method: 'POST', ...body({ conversation_id }) }),

  memories: (q = '', kind = '') => req<Memory[]>(`/api/memories?q=${encodeURIComponent(q)}${kind ? `&kind=${kind}` : ''}`),
  addMemory: (kind: string, content: string) => req<Memory>('/api/memories', { method: 'POST', ...body({ kind, content }) }),
  editMemory: (id: number, m: { kind?: string; content?: string }) => req<Memory>(`/api/memories/${id}`, { method: 'PATCH', ...body(m) }),
  deleteMemory: (id: number) => req(`/api/memories/${id}`, { method: 'DELETE' }),

  tasks: () => req<Task[]>('/api/tasks'),
  addTask: (t: { title: string; description?: string; due_at?: string | null; steps?: Step[] | null }) => req<Task>('/api/tasks', { method: 'POST', ...body(t) }),
  editTask: (id: number, t: Partial<Task>) => req<Task>(`/api/tasks/${id}`, { method: 'PATCH', ...body(t) }),
  approveTask: (id: number) => req(`/api/tasks/${id}/approve`, { method: 'POST' }),
  rerunTask: (id: number) => req(`/api/tasks/${id}/run`, { method: 'POST' }),
  cancelTask: (id: number) => req(`/api/tasks/${id}/cancel`, { method: 'POST' }),
  deleteTask: (id: number) => req(`/api/tasks/${id}`, { method: 'DELETE' }),

  approvals: (status = 'pending') => req<Approval[]>(`/api/approvals?status=${status}`),
  decide: (id: number, decision: 'approve' | 'deny') => req<Approval>(`/api/approvals/${id}/${decision}`, { method: 'POST' }),
  agentTools: () => req<{ tools: AgentTool[]; permissions?: Permissions; platform?: string; offline?: boolean }>('/api/agent/tools'),
  runTool: (tool: string, args: Record<string, unknown> = {}) => req<{ status: string; output?: unknown; error?: string }>('/api/tools/run', { method: 'POST', ...body({ tool, args }) }),
  activity: (limit = 200) => req<Activity[]>(`/api/activity?limit=${limit}`),
}

export type ChatEvent =
  | { type: 'conversation'; id: string }
  | { type: 'user_saved'; id: number }
  | { type: 'text'; delta: string }
  | { type: 'tool_start'; id: string; name: string; input: Record<string, unknown> }
  | { type: 'tool_result'; id: string; name: string; status: string; output?: unknown; error?: string; approval_id?: number }
  | { type: 'done'; message_id?: number; note?: string }
  | { type: 'stopped' }
  | { type: 'error'; kind: string; message: string }

/** POST /api/chat and stream server-sent events. */
export async function streamChat(conversation_id: string | null, message: string, onEvent: (e: ChatEvent) => void, signal: AbortSignal) {
  const res = await fetch('/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id, message }), signal,
  })
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try { detail = (await res.json()).detail } catch { /* ignore */ }
    throw new ApiError(detail, res.status)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2)
      for (const line of chunk.split('\n')) if (line.startsWith('data: ')) onEvent(JSON.parse(line.slice(6)))
    }
  }
}

/** ElevenLabs speech-to-text (via the backend). */
export async function transcribe(audio: Blob): Promise<string> {
  const fd = new FormData()
  const ext = audio.type.includes('mp4') ? 'm4a' : audio.type.includes('ogg') ? 'ogg' : 'webm'
  fd.append('audio', audio, `speech.${ext}`)
  let res: Response
  try { res = await fetch('/api/voice/stt', { method: 'POST', body: fd }) } catch { throw new ApiError('Backend not reachable', 0) }
  if (!res.ok) { let d = res.statusText; try { d = (await res.json()).detail } catch { /* ignore */ } throw new ApiError(d, res.status) }
  return (await res.json()).text as string
}

/** ElevenLabs text-to-speech (via the backend); resolves to an object URL of the MP3. */
export async function synthesize(text: string, signal?: AbortSignal): Promise<string> {
  const res = await fetch('/api/voice/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }), signal })
  if (!res.ok) { let d = res.statusText; try { d = (await res.json()).detail } catch { /* ignore */ } throw new ApiError(d, res.status) }
  return URL.createObjectURL(await res.blob())
}
