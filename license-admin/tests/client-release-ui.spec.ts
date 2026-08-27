import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('客户端更新管理界面', () => {
  const source = readFileSync(resolve(process.cwd(), 'src/views/updates/ClientReleaseView.vue'), 'utf8')
  const policySource = readFileSync(resolve(process.cwd(), 'src/views/versions/VersionPolicyView.vue'), 'utf8')

  it('只允许 Standard 与 License-Production 正式发布组合', () => {
    expect(source).toContain("product: 'iVRec'")
    expect(source).not.toContain("product: 'DDREC'")
    expect(source).toContain('/iVRec-...exe')
    expect(source).not.toContain('label="更新说明"')
    expect(source).not.toContain('编辑说明')
    expect(source).toContain('label="正式版本"')
    expect(source).toContain('label="Standard"')
    expect(source).toContain('label="License-Production"')
    expect(source).toContain('label="环境"')
    expect(source).not.toContain('label="local"')
    expect(source).not.toContain('label="dev"')
    expect(policySource).not.toContain('label="更新说明"')
  })
})
