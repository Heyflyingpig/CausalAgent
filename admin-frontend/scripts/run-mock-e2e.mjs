import { spawn } from 'node:child_process'
import { once } from 'node:events'
import process from 'node:process'

const root = process.cwd()
const vite = spawn(
  process.execPath,
  ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1'],
  { cwd: root, stdio: 'inherit' },
)

async function waitForVite() {
  /** 在限定时间内等待管理员 Vite 开发服务器就绪。 */
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    if (vite.exitCode !== null) {
      throw new Error(`Vite 提前退出，退出码 ${vite.exitCode}`)
    }
    try {
      const response = await fetch('http://127.0.0.1:5173/admin/database')
      if (response.ok) return
    } catch {
      // 启动窗口内连接失败是预期状态，继续短轮询。
    }
    await new Promise(resolve => setTimeout(resolve, 200))
  }
  throw new Error('等待 Vite 启动超时')
}

async function stopVite() {
  /** 只终止本脚本创建的精确 Vite 子进程。 */
  if (vite.exitCode !== null) return
  vite.kill()
  await Promise.race([
    once(vite, 'exit'),
    new Promise(resolve => setTimeout(resolve, 3_000)),
  ])
  if (vite.exitCode === null) vite.kill('SIGKILL')
}

let exitCode = 1
try {
  await waitForVite()
  const playwright = spawn(
    process.execPath,
    [
      'node_modules/@playwright/test/cli.js',
      'test',
      '--config',
      'playwright.mock.config.ts',
    ],
    { cwd: root, stdio: 'inherit' },
  )
  const [code] = await once(playwright, 'exit')
  exitCode = typeof code === 'number' ? code : 1
} finally {
  await stopVite()
}

process.exitCode = exitCode
