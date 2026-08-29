import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import SqlDigestTable from '../src/components/SqlDigestTable.vue'

describe('SqlDigestTable', () => {
  it('主表展示平均耗时，并按平均耗时、累计耗时降序排列', async () => {
    const wrapper = mount(SqlDigestTable, {
      props: {
        statements: [
          {
            digest_text: 'SELECT * FROM users WHERE id = ?',
            total_seconds: 1.2,
            avg_seconds: 0.12,
          },
          {
            digest_text: 'SELECT * FROM custom_table WHERE tenant_id = ?',
            total_seconds: 0.75,
            avg_seconds: 0.25,
          },
          {
            digest_text: 'SELECT * FROM sessions WHERE user_id = ?',
            total_seconds: 2.4,
            avg_seconds: 0.12,
          },
          {
            digest_text: 'SELECT * FROM user_files WHERE user_id = ?',
            total_seconds: 9,
            avg_seconds: 'invalid',
          },
        ],
      },
      global: {
        plugins: [ElementPlus],
      },
    })
    await nextTick()
    await nextTick()

    const rows = wrapper.findAll('.el-table__body-wrapper tbody tr')
    expect(wrapper.text()).toContain('平均耗时')
    expect(rows).toHaveLength(4)
    expect(rows[0].text()).toContain('推断：查询 custom_table 数据')
    expect(rows[0].text()).toContain('0.25 秒')
    expect(rows[1].text()).toContain('读取聊天会话')
    expect(rows[1].text()).toContain('0.12 秒')
    expect(rows[2].text()).toContain('读取用户身份或权限')
    expect(rows[2].text()).toContain('0.12 秒')
    expect(rows[3].text()).toContain('读取用户上传文件')
    expect(rows[3].text()).toContain('—')

    await new Promise(resolve => window.setTimeout(resolve, 100))
    wrapper.unmount()
  })

  it('默认只展示业务语义，点击后完整展示原始 Digest 字段', async () => {
    const wrapper = mount(SqlDigestTable, {
      attachTo: document.body,
      props: {
        statements: [{
          digest_text: 'SELECT * FROM users WHERE id = ?',
          count_star: 10,
          total_seconds: 1.2,
          avg_seconds: 0.12,
          rows_examined: 10,
          rows_sent: 1,
        }],
      },
      global: {
        plugins: [ElementPlus],
      },
    })
    await nextTick()
    await nextTick()

    expect(wrapper.text()).toContain('读取用户身份或权限')
    expect(wrapper.text()).toContain('代码确认')
    expect(document.body.textContent).not.toContain('SELECT * FROM users WHERE id = ?')

    await wrapper.get('button').trigger('click')
    await nextTick()

    expect(document.body.textContent).toContain('SQL详情')
    expect(document.body.textContent).toContain('SELECT * FROM users WHERE id = ?')
    expect(document.body.textContent).toContain('Digest 模板')
    expect(document.body.textContent).toContain('执行次数')
    expect(document.body.textContent).toContain('累计总耗时')
    expect(document.body.textContent).toContain('平均耗时')
    expect(document.body.textContent).toContain('扫描行')
    expect(document.body.textContent).toContain('返回行')
    expect(document.body.textContent).toContain('判断依据')
    expect(document.body.textContent).toContain('app/auth/service.py')

    await new Promise(resolve => window.setTimeout(resolve, 100))
    wrapper.unmount()
  })
})
