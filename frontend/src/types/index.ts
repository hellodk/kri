export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface User {
  id: string
  email: string
  role: 'admin' | 'operator' | 'viewer'
}

export interface Tag {
  key: string
  value: string
  source: 'system' | 'user'
}

export interface Node {
  id: string
  minion_id: string
  hostname: string | null
  ip_address: string | null
  os_version: string | null
  hardware_model: string | null
  status: 'online' | 'offline' | 'stale' | 'unknown'
  drift_score: number
  last_seen_at: string | null
  tags: Tag[]
  maintenance_mode: boolean
  bootstrap_ip?: string | null
  xcode_version?: string | null
  macos_version?: string | null
  // SSH credential metadata (present when loaded via detail endpoint)
  ssh_username?: string | null
  ssh_auth_mode?: 'password' | 'key'
  has_ssh_password?: boolean
  has_ssh_key?: boolean
}

export interface NodeDetail extends Node {
  os_build: string | null
  cpu_cores: number | null
  ram_gb: number | null
  storage_gb: number | null
  first_seen_at: string
  created_at: string
  bootstrap_status: 'unregistered' | 'pending' | 'bootstrapping' | 'completed' | 'failed'
  bootstrap_ip: string | null
  bootstrap_error: string | null
  bootstrap_logs: string | null
  ssh_username: string | null
  ssh_auth_mode: 'password' | 'key'
  has_ssh_password: boolean
  has_ssh_key: boolean
  maintenance_mode: boolean
}

export interface FleetOverview {
  total_nodes: number
  online: number
  stale: number
  offline: number
  unknown: number
  avg_drift_score: number
  nodes_clean: number
  nodes_low: number
  nodes_medium: number
  nodes_high: number
  nodes_critical: number
  last_updated: string
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  per_page: number
}

export interface DriftSummary {
  node_id: string
  hostname: string | null
  drift_score: number
  severity: string
  computed_at: string | null
  baseline_name: string | null
}

export interface DriftRecord {
  node_id: string
  baseline_id: string | null
  baseline_name: string | null
  computed_at: string
  drift_score: number
  severity: string
  missing_packages: Array<{ name: string; required_version: string | null }>
  extra_packages: Array<{ name: string; installed_version: string }>
  version_mismatches: Array<{ name: string; expected: string; actual: string }>
  service_drift: Array<{ name: string; expected: string; actual: string }>
  config_drift: unknown[]
}

export interface SBOMScan {
  id: string
  node_id: string
  syft_version: string | null
  format: string
  scanned_at: string
  component_count: number | null
}

export interface SBOMComponent {
  id: number
  scan_id: string
  node_id: string
  name: string
  version: string | null
  purl: string | null
  component_type: string | null
  licenses: string[]
  cpes: string[]
}

export interface SBOMSearchResult {
  name: string
  version: string | null
  purl: string | null
  component_type: string | null
  hostname: string
  node_id: string
  scan_id: string
  scanned_at: string
}

export interface Group {
  id: string
  name: string
  description: string | null
  type: 'static' | 'dynamic'
  predicate: Record<string, unknown> | null
  member_count: number
  created_at: string
}

export interface ExecutionJob {
  id: string
  salt_jid: string | null
  type: string
  target_type: string
  target_id: string | null
  triggered_by: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at: string | null
  completed_at: string | null
}

export interface ExecutionResult {
  id: string
  job_id: string
  node_id: string
  status: string
  exit_code: number | null
  stdout: string | null
  stderr: string | null
  completed_at: string
}

export interface SearchResult {
  id: string
  hostname: string | null
  minion_id: string
  status: string
}
