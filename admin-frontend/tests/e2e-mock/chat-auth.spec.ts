import { readFile } from 'node:fs/promises'
import { expect, test } from '@playwright/test'


const repositoryRoot = new URL('../../../', import.meta.url)


test('管理员可停留在聊天页，普通用户看不到后台入口且越权提示只显示一次', async ({
  page,
}) => {
  let role: 'user' | 'admin' = 'admin'
  const [chatHtml, chatScript, chatStyle, markedScript] = await Promise.all([
    readFile(new URL('app/static/chat.html', repositoryRoot), 'utf8'),
    readFile(new URL('app/static/js/script.js', repositoryRoot), 'utf8'),
    readFile(new URL('app/static/css/style.css', repositoryRoot), 'utf8'),
    readFile(new URL('app/static/js/marked.min.js', repositoryRoot), 'utf8'),
  ])

  await page.route(/^http:\/\/127\.0\.0\.1:5173\/(?:\?.*)?$/, route => route.fulfill({
    contentType: 'text/html; charset=utf-8',
    body: chatHtml,
  }))
  await page.route('**/static/js/script.js', route => route.fulfill({
    contentType: 'application/javascript; charset=utf-8',
    body: chatScript,
  }))
  await page.route('**/static/js/marked.min.js', route => route.fulfill({
    contentType: 'application/javascript; charset=utf-8',
    body: markedScript,
  }))
  await page.route('**/static/css/style.css', route => route.fulfill({
    contentType: 'text/css; charset=utf-8',
    body: chatStyle,
  }))
  await page.route('https://unpkg.com/**', route => route.abort())
  await page.route('**/api/check_auth', route => route.fulfill({
    json: {
      isLoggedIn: true,
      username: role === 'admin' ? 'mock-admin' : 'mock-user',
      role,
      csrf_token: 'mock-csrf',
    },
  }))
  await page.route('**/api/sessions', route => route.fulfill({ json: [] }))
  await page.route('**/api/files', route => route.fulfill({ json: [] }))

  await page.goto('/')
  await expect(page).toHaveURL('http://127.0.0.1:5173/')
  await expect(page.locator('#mainContainer')).toBeVisible()
  await page.locator('#userAvatar').evaluate(element => (element as HTMLElement).click())
  await expect(page.getByRole('button', { name: '管理后台' })).toBeVisible()

  role = 'user'
  await page.reload()
  await expect(page.locator('#mainContainer')).toBeVisible()
  await page.locator('#userAvatar').evaluate(element => (element as HTMLElement).click())
  await expect(page.getByRole('button', { name: '管理后台' })).toBeHidden()

  const dialogPromise = page.waitForEvent('dialog')
  await page.goto('/?notice=admin_required')
  const dialog = await dialogPromise
  expect(dialog.message()).toBe('无管理员权限')
  await dialog.accept()
  await expect(page).toHaveURL('http://127.0.0.1:5173/')
})
