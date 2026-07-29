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

export interface CursorPage<T> {
  items: T[]
  limit: number
  has_more: boolean
  next_cursor: string | null
}

export interface OverviewMetric {
  key: string
  label: string
  value: number
  is_estimate: boolean
  source_alias: string
}

export interface SnapshotSummary {
  snapshot_key: string
  observed_at: string | null
  refresh_requested_at: string | null
  status: HealthStatus
  warning: string | null
  source_alias: string
}

export interface BusinessOverview {
  metrics: OverviewMetric[]
  snapshots: SnapshotSummary[]
  observed_at: string
  source_alias: string
  is_estimate: boolean
}

export interface AdminUser {
  id: number
  username: string
  role: 'user' | 'admin'
  is_active: boolean
  created_at: string
  last_login_at: string | null
  auth_version?: number
  password_changed_at?: string | null
}

export type UserOperationAction = 'set_active' | 'set_role' | 'set_password'

export interface UserOperationPreviewItem {
  id: number
  username: string
  current: { role: 'user' | 'admin'; is_active: boolean }
  next: Partial<{
    role: 'user' | 'admin'
    is_active: boolean
    password_changed: boolean
  }>
  blockers: string[]
}

export interface UserOperationPreview {
  action: UserOperationAction
  target_count: number
  items: UserOperationPreviewItem[]
  can_execute: boolean
  requires_reauthentication: boolean
  batch_limit: number
}

export interface AdminOperationResult {
  operation_id: string
  operation_type: string
  target_count: number
  replayed: boolean
  items?: Array<{
    id: number
    username: string
    changed: boolean
    role: 'user' | 'admin'
    is_active: boolean
    auth_version: number
  }>
  deleted?: boolean
  user_id?: number
  username?: string
  file_id?: number
  filename?: string
  blob_deleted?: boolean
}

export interface UserDeleteImpact {
  user: AdminUser
  impact: Record<string, number>
  can_delete: boolean
  blockers: string[]
  requires_confirmation: string
  requires_reauthentication: boolean
  synchronous_delete_limit: number
}

export interface AdminSession {
  id: string
  user_id: number
  username: string
  title: string | null
  created_at: string
  last_activity_at: string
  message_count: number
  is_archived: boolean
  archived_at: string | null
}

export interface AdminMessage {
  id: number
  session_id: string
  user_id: number
  username: string
  message_type: 'user' | 'ai'
  content_preview: string
  content_length: number
  has_attachment: boolean
  attachment_count: number
  created_at: string
}

export interface AdminAttachment {
  id: number
  message_id: number
  attachment_type: string
  content_size: number
  created_at: string
}

export interface AdminJob {
  row_id?: number
  job_id: string
  user_id: number
  username: string
  session_id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'
  worker_id: string | null
  attempt_count: number
  max_attempts: number
  error_preview?: string | null
  has_input?: boolean
  has_result: boolean
  has_error?: boolean
  locked_at: string | null
  heartbeat_at: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  chat_saved_at: string | null
}

export interface AdminJobEvent {
  id: number
  job_id: string
  event_type: string
  created_at: string
  has_payload: boolean
}

export interface AdminFile {
  id: number
  user_id: number
  username: string
  filename: string
  original_filename: string
  mime_type: string
  file_size: number
  upload_timestamp: string
  last_accessed_at: string
  access_count: number
}

export interface FileDeleteImpact {
  file: AdminFile
  impact: {
    database_rows: number
    blob_bytes: number
    owner_active_jobs: number
  }
  can_delete: boolean
  blockers: string[]
  requires_confirmation: string
  requires_reauthentication: boolean
  recycle_bin: false
}

export interface SensitiveContentChunk {
  content: string
  offset: number
  limit: number
  total_length: number
  complete: boolean
  next_offset: number | null
  kind?: 'input' | 'result' | 'error'
}

export interface CsvPreview {
  file_id: number
  filename: string
  mime_type: string
  encoding: string
  columns: string[]
  rows: string[][]
  truncated: boolean
  limits: {
    bytes: number
    rows: number
    columns: number
    cell_chars: number
  }
}

export interface DeepAuditCheck {
  key: string
  label: string
  status: HealthStatus
  summary: string
  details: unknown
}

export interface DeepAuditSnapshot extends SnapshotMeta {
  mode: 'deep'
  auto_scheduled?: boolean
  sample_limit?: number
  query_timeout_ms?: number
  checks: DeepAuditCheck[]
}
