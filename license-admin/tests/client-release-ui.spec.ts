import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('客户端更新管理界面', () => {
  const source = readFileSync(resolve(process.cwd(), 'src/views/updates/ClientReleaseView.vue'), 'utf8')
  const policySource = readFileSync(resolve(process.cwd(), 'src/views/versions/VersionPolicyView.vue'), 'utf8')

  it('不再提供更新内容编辑，但保留Edition和环境发布字段', () => {
    expect(source).not.toContain('label="更新说明"')
    expect(source).not.toContain('编辑说明')
    expect(source).toContain('label="Edition"')
    expect(source).toContain('label="环境"')
    expect(policySource).not.toContain('label="更新说明"')
  })
})
