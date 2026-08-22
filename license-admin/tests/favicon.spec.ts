import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('管理端品牌页签', () => {
  it('使用随生产构建发布的DD Rec favicon和统一标题', () => {
    const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')
    expect(html).toContain('%BASE_URL%favicon.svg')
    expect(html).toContain('<title>DD Rec 授权管理</title>')
    expect(existsSync(resolve(process.cwd(), 'public/favicon.svg'))).toBe(true)
  })
})
