export type HealthStatus = 'healthy' | 'warning' | 'error' | 'unknown'
export type MonitorSource = 'database' | 'environment' | 'default'

export interface SnapshotMeta {
  status?: HealthStatus
  observed_at?: string | null
  source_role?: string
  source_alias?: string
  is_estimate?: boolean
  is_stale?: boolean
  refresh_pending?: boolean
  warning?: string | null
  [key: string]: unknown
}

export interface DashboardData {
  realtime: SnapshotMeta
  sql_performance: SnapshotMeta
  capacity: SnapshotMeta
  integrity: SnapshotMeta
  refresh_policy: Record<string, unknown>
}

export type MonitorField =
  | 'auto_refresh_enabled'
  | 'realtime_interval_seconds'
  | 'sql_interval_seconds'
  | 'table_capacity_interval_seconds'
  | 'slow_query_warning_delta'
  | 'integrity_enabled'
  | 'integrity_interval_seconds'

export type MonitorValueMap = Record<MonitorField, boolean | number>
export type MonitorOverrideMap = Record<MonitorField, boolean | number | null>

export interface MonitorLimit {
  type: 'boolean' | 'integer'
  minimum?: number
  maximum?: number
}

export interface MonitorSettings {
  version: number | null
  overrides: MonitorOverrideMap
  effective: MonitorValueMap
  sources: Record<MonitorField, MonitorSource>
  limits: Record<MonitorField, MonitorLimit>
  updated_by: { id: number; username: string | null } | null
  updated_at: string | null
  state: 'current' | 'degraded'
  warning: string | null
}

export interface AuditEvent {
  id: number
  actor_user_id: number | null
  actor_username: string
  action: string
  target_id: string | null
  old_values: Record<string, unknown> | null
  new_values: Record<string, unknown> | null
  result: 'success' | 'rejected' | 'failed'
  error_code: string | null
  request_id: string
  created_at: string
}

export interface Identity {
  isLoggedIn: boolean
  username?: string
  role?: 'user' | 'admin'
  csrf_token?: string
}
