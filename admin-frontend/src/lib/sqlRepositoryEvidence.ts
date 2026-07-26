import type { SqlBusinessMeaning } from './sqlSemantics'

/** 构造绑定仓库调用点的确认语义，避免把代码证据降格为表名推断。 */
function confirmedMeaning(
  module: string,
  action: string,
  description: string,
  evidence: string,
): SqlBusinessMeaning {
  return { module, action, description, confidence: 'confirmed', evidence }
}

/** 识别当前仓库监控、认证和任务看板中的稳定 SQL 签名并绑定实际函数证据。 */
export function meaningForRepositoryQuery(normalizedSql: string): SqlBusinessMeaning | null {
  if (normalizedSql.startsWith('SHOW GLOBAL VARIABLES')) {
    return confirmedMeaning(
      '数据库监控',
      '读取连接上限与慢查询配置',
      'monitor 读取 max_connections、slow_query_log 和 long_query_time 等全局配置。',
      'Database/inspection.py · _show_values()，由 inspect_connections() / inspect_slow_queries() 调用',
    )
  }
  if (normalizedSql.startsWith('SHOW GLOBAL STATUS')) {
    return confirmedMeaning(
      '数据库监控',
      '读取连接与慢查询运行状态',
      'monitor 读取当前连接数、运行线程、历史峰值、Slow_queries 和 Uptime。',
      'Database/inspection.py · _show_values()，由 inspect_connections() / inspect_slow_queries() 调用',
    )
  }
  if (
    normalizedSql.includes('PERFORMANCE_SCHEMA')
    && normalizedSql.includes('EVENTS_STATEMENTS_SUMMARY_BY_DIGEST')
  ) {
    return confirmedMeaning(
      'SQL 性能监控',
      '采集高负载 SQL 摘要',
      'monitor 从 Performance Schema 读取归一化 Digest，并按累计总耗时排序。',
      'Database/inspection.py · inspect_slow_queries()',
    )
  }
  if (normalizedSql.includes('SELECT GET_LOCK')) {
    return confirmedMeaning(
      '监控调度',
      '获取监控采集命名锁',
      'monitor 在采集前竞争 MySQL 命名锁，避免多进程重复采集同一类快照。',
      'Database/monitoring.py · collect_snapshot()',
    )
  }
  if (normalizedSql.includes('SELECT RELEASE_LOCK')) {
    return confirmedMeaning(
      '监控调度',
      '释放监控采集命名锁',
      'monitor 完成或退出采集后释放对应的 MySQL 命名锁。',
      'Database/monitoring.py · collect_snapshot()',
    )
  }
  if (normalizedSql.includes('VERSION ( ) AS VERSION') && normalizedSql.includes('DATABASE_TIME')) {
    return confirmedMeaning(
      '数据库监控',
      '检查主库连接与版本',
      'realtime 采集确认主库可连接，并读取 MySQL 版本和数据库时间。',
      'Database/inspection.py · inspect_primary()',
    )
  }
  if (normalizedSql.includes('@@GLOBAL . SERVER_UUID') || normalizedSql.includes('@@GLOBAL.SERVER_UUID')) {
    return confirmedMeaning(
      'SQL 性能监控',
      '确认慢查询计数来源实例',
      '采集器读取并散列 server_uuid，判断相邻采集窗口是否仍来自同一个 MySQL 实例。',
      'Database/inspection.py · _server_instance_id() / inspect_slow_queries()',
    )
  }
  if (
    normalizedSql.startsWith('SELECT')
    && normalizedSql.includes('FROM DATABASE_MONITOR_SNAPSHOTS')
    && normalizedSql.includes('PAYLOAD_JSON')
    && normalizedSql.includes('DATABASE_NOW')
  ) {
    return confirmedMeaning(
      '数据库看板',
      '读取四类共享监控快照',
      'Web 与 monitor 一次读取 realtime、sql_performance、capacity、integrity 四类快照及刷新状态。',
      'Database/monitoring.py · _read_snapshot_records()',
    )
  }
  if (
    normalizedSql.startsWith('INSERT INTO DATABASE_MONITOR_SNAPSHOTS')
    && normalizedSql.includes('PAYLOAD_JSON')
    && normalizedSql.includes('ON DUPLICATE KEY UPDATE')
  ) {
    return confirmedMeaning(
      '数据库监控',
      '写入本轮监控采集结果',
      'monitor 将一个分层采集结果写入共享快照，存在同名快照时更新 payload 和采集时间。',
      'Database/monitoring.py · collect_snapshot()',
    )
  }
  if (
    normalizedSql.includes('FROM DATABASE_MONITOR_SETTINGS AS S')
    && normalizedSql.includes('UPDATED_BY_USERNAME')
  ) {
    return confirmedMeaning(
      '监控配置',
      '读取在线监控配置和修改人',
      '配置解析服务读取七项数据库覆盖值、版本以及最后修改管理员。',
      'Database/monitor_settings.py · _read_settings_row()',
    )
  }
  if (
    normalizedSql.includes('FROM ANALYSIS_JOBS')
    && normalizedSql.includes('AS QUEUED')
    && normalizedSql.includes('AS MAX_ATTEMPTS_RUNNING')
  ) {
    return confirmedMeaning(
      'Worker / Job 监控',
      '汇总活动任务健康状态',
      'realtime 采集统计 queued、running、stale 和达到最大尝试次数仍运行的任务。',
      'app/agent/job_service.py · get_worker_snapshot_report()',
    )
  }
  if (
    normalizedSql.includes('FROM ANALYSIS_JOBS')
    && normalizedSql.includes('WORKER_ID')
    && normalizedSql.includes('HEARTBEAT_AT')
    && normalizedSql.includes('STATUS IN')
  ) {
    return confirmedMeaning(
      'Worker / Job 监控',
      '读取活动任务明细',
      'realtime 采集读取 queued/running 任务的 Worker、心跳、尝试次数和创建时间。',
      'app/agent/job_service.py · get_worker_snapshot_report()',
    )
  }
  if (
    normalizedSql.startsWith('SELECT')
    && normalizedSql.includes('USERNAME')
    && normalizedSql.includes('ROLE')
    && normalizedSql.includes('IS_ACTIVE')
    && normalizedSql.includes('FROM USERS')
    && normalizedSql.includes('WHERE ID = ?')
  ) {
    return confirmedMeaning(
      '登录会话校验',
      '按用户 ID 复核身份、角色和启用状态',
      '每次恢复会话或访问受保护页面时从主库重新确认用户仍存在、已启用且角色有效。',
      'app/auth/service.py · find_user_by_id()；app/auth/session_guard.py · get_current_session_user()',
    )
  }
  return null
}
