// Shared shapes for data crossing the /api boundary. Kept loose (fields the UI
// doesn't read are typed `unknown` rather than enumerated) since the backend
// is the source of truth and these exist to catch typos, not to model it in full.

export type Provider = 'google_genai' | 'openai' | 'anthropic' | (string & {})

export interface ProvidersResponse {
  default: Provider
  supported: Provider[]
}

export interface ImprovePromptResponse {
  improved: string
  changes?: string[]
}

export interface Source {
  url: string
  title?: string
}

export interface Citation {
  url: string
  title?: string
}

export interface PlotlySpec {
  data?: unknown[]
  layout?: Record<string, unknown>
}

export interface Chart {
  format: 'plotly' | 'png'
  title?: string
  data?: string // base64, for png
  spec?: PlotlySpec // for plotly
}

export interface ReportData {
  report: string
  citations?: Citation[]
  charts?: Chart[]
  total_tool_calls?: number
  loops?: number
}

export interface ConfidenceEntry {
  score?: number
  reason?: string
  gaps?: string[]
}

// Agent trace events, discriminated by `name`. Every field beyond `name` is
// event-specific, so this stays a loose union rather than one big interface.
export interface AgentEventBase {
  name: string
  timestamp?: string
  [key: string]: unknown
}

export interface NodeStartEvent extends AgentEventBase {
  name: 'node_start'
  node: string
}

// `agent` is set while sub-agents are researching in parallel, and names which
// one made the call. Absent outside a fan-out.
export interface ToolCallEvent extends AgentEventBase {
  name: 'tool_call'
  tool: string
  input?: Record<string, unknown>
  agent?: string
}

export interface ToolResultEvent extends AgentEventBase {
  name: 'tool_result'
  tool: string
  result_count?: number
  sources?: Source[]
  agent?: string
}

export interface CodeRunEvent extends AgentEventBase {
  name: 'code_run'
  purpose?: string
  attempt?: number
  code?: string
}

export interface ChartReadyEvent extends AgentEventBase {
  name: 'chart_ready'
  index: number
  title?: string
}

export interface ResultsFilteredEvent extends AgentEventBase {
  name: 'results_filtered'
  dropped: number
  terms: string[]
  agent?: string
}

export interface ToolSkippedEvent extends AgentEventBase {
  name: 'tool_skipped'
  tool: string
  input?: Record<string, unknown>
  agent?: string
}

// --- parallel sub-agents ---
// Execute fans out one agent per sub-question; these bracket that fan-out.

export interface FanoutEvent extends AgentEventBase {
  name: 'fanout'
  agents: number
  questions: string[]
  budget: number
}

export interface SubagentStartEvent extends AgentEventBase {
  name: 'subagent_start'
  agent: string
  question: string
}

export interface SubagentDoneEvent extends AgentEventBase {
  name: 'subagent_done'
  agent: string
  question: string
  tool_calls: number
  findings: number
}

export interface MergedEvent extends AgentEventBase {
  name: 'merged'
  agents: number
  tool_calls: number
  findings: number
}

export interface GateEvent extends AgentEventBase {
  name: 'gate'
  decision: 'execute' | 'synthesize'
  score?: number
  threshold: number
  reason?: string
}

export interface ErrorEvent extends AgentEventBase {
  name: 'error'
  message: string
}

export interface ConfidenceCheckEvent extends AgentEventBase, ConfidenceEntry {
  name: 'confidence_check'
}

export interface ReportReadyEvent extends AgentEventBase, ReportData {
  name: 'report_ready'
}

export type AgentEvent =
  | NodeStartEvent
  | ToolCallEvent
  | ToolResultEvent
  | CodeRunEvent
  | ChartReadyEvent
  | ResultsFilteredEvent
  | ToolSkippedEvent
  | FanoutEvent
  | SubagentStartEvent
  | SubagentDoneEvent
  | MergedEvent
  | GateEvent
  | ErrorEvent
  | ConfidenceCheckEvent
  | ReportReadyEvent

export type AgentStatus = 'idle' | 'running' | 'done' | 'error'

export interface StreamResearchBody {
  goal: string
  provider?: string
  model?: string
  api_key?: string
  include_keywords?: string[]
  exclude_keywords?: string[]
}
