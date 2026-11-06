export type Metric = number | 'UNKNOWN' | 'NOT_APPLICABLE'
export type Architecture = 'single' | 'multi'
export const architectures = ['single', 'multi'] as const
export const categories = ['A1', 'A2', 'A3', 'B1', 'B2', 'S1', 'R1', 'E1'] as const
export const statuses = [
  'COMPLETED',
  'PARTIAL',
  'FAILED',
  'NOT_RUN',
  'WAITING_INPUT',
  'RUNNING',
  'UNKNOWN',
] as const
export type Evidence = 'FIXTURE_EVALUATION' | 'LIVE_LLM_EVALUATION'

interface Outcome {
  successes: number
  denominator: number
}
interface ArchitectureSummary extends Outcome {
  success_rate: number
  success_ci95: [Metric, Metric]
  per_category: Record<string, Outcome>
  machine_latency_p50: Metric
  machine_latency_p95: Metric
  model_calls: Metric
  tool_calls: Metric
  actual_bill_cny: Metric
  input_tokens: Metric
  output_tokens: Metric
  partial_count: number
  not_run_count: number
  harness_failure_count: number
  diagnostics: Record<string, Metric>
}
export interface Episode {
  task_id: string
  repetition_id: number | null
  architecture: Architecture
  category: string
  success: boolean
  run_status: string
  oracle_rules: string[]
  error_class: string
  machine_seconds: Metric
  model_calls: Metric
  tool_calls: Metric
  business_effects: Record<string, Metric>
  observed_safety_rejections: Metric
  error_code?: string
}
interface Pilot {
  single_success: Metric
  multi_success: Metric
  tasks_per_architecture: Metric
  model_requests: Metric
}
export interface StudioReport {
  version: 1
  run: {
    run_id: string
    git_commit: string
    dataset_sha256: string
    manifest_sha256: string
    started_at: string
    completed_at: string
    environment: Record<'os' | 'architecture' | 'python' | 'postgresql', string>
  }
  comparison: Record<Architecture, ArchitectureSummary> & {
    evidence_class: Evidence
    paid_provider_requests: Metric
    paired_episodes: number
    cluster_count: number
    bootstrap: { unit: 'task_id'; repetitions: number; seed: number }
    multi_minus_single: {
      success_rate: number
      success_ci95: [Metric, Metric]
      model_calls: Metric
      tool_calls: Metric
      mean_machine_seconds: Metric
    }
  }
  episodes: Episode[]
  historical_live: null | {
    evidence_class: 'LIVE_LLM_EVALUATION'
    scope: 'HISTORICAL_REVIEWED_AGGREGATE'
    git_commit: string
    dataset_sha256: string
    source_sha256: string
    actual_bill_cny: Metric
    first: Pilot
    second: Pilot
    reviewed_failure: null | {
      task_id: string
      architecture: Architecture
      run_status: string
      error_code: string
      business_effects: Record<string, Metric> | 'UNKNOWN'
    }
  }
}

const evidenceClasses = ['FIXTURE_EVALUATION', 'LIVE_LLM_EVALUATION']
const summaryMetrics = [
  'machine_latency_p50',
  'machine_latency_p95',
  'model_calls',
  'tool_calls',
  'actual_bill_cny',
  'input_tokens',
  'output_tokens',
]
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}
function count(value: unknown): value is number {
  return finite(value) && Number.isInteger(value) && value >= 0
}
function metric(value: unknown): value is Metric {
  return finite(value) || value === 'UNKNOWN' || value === 'NOT_APPLICABLE'
}
function metricMap(value: unknown) {
  return record(value) && Object.values(value).every(metric)
}
function interval(value: unknown) {
  return Array.isArray(value) && value.length === 2 && value.every(metric)
}
function outcome(value: unknown): value is Outcome {
  return (
    record(value) &&
    count(value.successes) &&
    count(value.denominator) &&
    value.successes <= value.denominator
  )
}
function summary(value: unknown) {
  return (
    record(value) &&
    outcome(value) &&
    value.denominator > 0 &&
    value.success_rate === value.successes / value.denominator &&
    interval(value.success_ci95) &&
    metricMap(value.diagnostics) &&
    record(value.per_category) &&
    Object.values(value.per_category).every(outcome) &&
    summaryMetrics.every((key) => metric(value[key])) &&
    ['partial_count', 'not_run_count', 'harness_failure_count'].every((key) => count(value[key]))
  )
}
function episode(value: unknown): value is Episode {
  return (
    record(value) &&
    typeof value.task_id === 'string' &&
    typeof value.category === 'string' &&
    categories.some((category) => category === value.category) &&
    new RegExp(`^eval_(dev|test)_${value.category}_[0-9]{2}$`).test(value.task_id) &&
    architectures.some((arch) => arch === value.architecture) &&
    count(value.repetition_id) &&
    typeof value.success === 'boolean' &&
    statuses.some((status) => status === value.run_status) &&
    (value.run_status !== 'NOT_RUN' || !value.success) &&
    Array.isArray(value.oracle_rules) &&
    value.oracle_rules.every((rule) => typeof rule === 'string') &&
    typeof value.error_class === 'string' &&
    (value.error_code === undefined || typeof value.error_code === 'string') &&
    metricMap(value.business_effects) &&
    ['machine_seconds', 'model_calls', 'tool_calls', 'observed_safety_rejections'].every((key) =>
      metric(value[key]),
    )
  )
}
function historical(value: unknown) {
  if (value === null) return true
  if (
    !record(value) ||
    value.evidence_class !== 'LIVE_LLM_EVALUATION' ||
    value.scope !== 'HISTORICAL_REVIEWED_AGGREGATE' ||
    !metric(value.actual_bill_cny) ||
    !['git_commit', 'dataset_sha256', 'source_sha256'].every(
      (key) => typeof value[key] === 'string',
    )
  )
    return false
  const failure = value.reviewed_failure
  return (
    [value.first, value.second].every(
      (pilot) =>
        record(pilot) &&
        ['single_success', 'multi_success', 'tasks_per_architecture', 'model_requests'].every(
          (key) => metric(pilot[key]),
        ),
    ) &&
    (failure === null ||
      (record(failure) &&
        typeof failure.task_id === 'string' &&
        typeof failure.error_code === 'string' &&
        architectures.some((arch) => arch === failure.architecture) &&
        statuses.some((status) => status === failure.run_status) &&
        (failure.business_effects === 'UNKNOWN' || metricMap(failure.business_effects))))
  )
}

export function parseStudioReport(input: unknown): StudioReport {
  const invalid = () => new Error('无法读取此版本的评测报告。')
  if (!record(input) || input.version !== 1) throw invalid()
  const { run, comparison, episodes, historical_live } = input
  if (
    !record(run) ||
    ![
      'run_id',
      'git_commit',
      'dataset_sha256',
      'manifest_sha256',
      'started_at',
      'completed_at',
    ].every((key) => typeof run[key] === 'string') ||
    !record(run.environment) ||
    !['os', 'architecture', 'python', 'postgresql'].every(
      (key) => typeof (run.environment as Record<string, unknown>)[key] === 'string',
    ) ||
    !record(comparison) ||
    !evidenceClasses.some((kind) => kind === comparison.evidence_class) ||
    !metric(comparison.paid_provider_requests) ||
    !count(comparison.paired_episodes) ||
    comparison.paired_episodes === 0 ||
    !count(comparison.cluster_count) ||
    !architectures.every((arch) => summary(comparison[arch])) ||
    !record(comparison.bootstrap) ||
    comparison.bootstrap.unit !== 'task_id' ||
    !count(comparison.bootstrap.repetitions) ||
    !count(comparison.bootstrap.seed) ||
    !record(comparison.multi_minus_single) ||
    !finite(comparison.multi_minus_single.success_rate) ||
    !interval(comparison.multi_minus_single.success_ci95) ||
    !metric(comparison.multi_minus_single.mean_machine_seconds) ||
    !metric(comparison.multi_minus_single.model_calls) ||
    !metric(comparison.multi_minus_single.tool_calls) ||
    !Array.isArray(episodes) ||
    !episodes.every(episode) ||
    !historical(historical_live)
  )
    throw invalid()

  const pairs = new Map<string, Set<Architecture>>()
  for (const row of episodes) {
    const key = `${row.task_id}:${row.repetition_id}`
    const members = pairs.get(key) ?? new Set()
    if (members.has(row.architecture)) throw invalid()
    members.add(row.architecture)
    pairs.set(key, members)
  }
  if (
    pairs.size !== comparison.paired_episodes ||
    new Set(episodes.map((row) => row.task_id)).size !== comparison.cluster_count ||
    [...pairs.values()].some((members) => members.size !== 2)
  )
    throw invalid()
  for (const arch of architectures) {
    const rows = episodes.filter((row) => row.architecture === arch)
    const value = comparison[arch] as ArchitectureSummary
    if (
      value.denominator !== rows.length ||
      value.successes !== rows.filter((row) => row.success).length ||
      Object.keys(value.per_category).length !== new Set(rows.map((row) => row.category)).size
    )
      throw invalid()
    for (const category of categories) {
      const group = rows.filter((row) => row.category === category)
      const recorded = value.per_category[category]
      if (
        group.length === 0
          ? recorded !== undefined
          : recorded?.denominator !== group.length ||
            recorded.successes !== group.filter((row) => row.success).length
      )
        throw invalid()
    }
  }
  const single = comparison.single as ArchitectureSummary
  const multi = comparison.multi as ArchitectureSummary
  if (comparison.multi_minus_single.success_rate !== multi.success_rate - single.success_rate)
    throw invalid()
  return input as unknown as StudioReport
}

export function formatMetric(value: Metric | undefined, suffix = '', digits = 0) {
  return typeof value === 'number'
    ? `${value.toLocaleString('en-US', { maximumFractionDigits: digits })}${suffix}`
    : (value ?? 'UNKNOWN')
}

export interface EpisodeFilters {
  task?: string
  category?: string
  architecture?: string
  status?: string
  verdict?: 'attention' | 'failed' | 'all'
}
export function filterEpisodes(rows: Episode[], filters: EpisodeFilters) {
  return rows.filter(
    (row) =>
      (!filters.task || row.task_id.toLowerCase().includes(filters.task.trim().toLowerCase())) &&
      (!filters.category || row.category === filters.category) &&
      (!filters.architecture || row.architecture === filters.architecture) &&
      (!filters.status || row.run_status === filters.status) &&
      (filters.verdict !== 'attention' || !row.success || row.run_status !== 'COMPLETED') &&
      (filters.verdict !== 'failed' || !row.success),
  )
}
