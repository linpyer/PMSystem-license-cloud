import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import StatusTag from '@/components/StatusTag.vue'

const render = (status: string) => mount(StatusTag, { props: { status }, global: { plugins: [ElementPlus] } })

describe('状态标签', () => {
  it('显示有效状态文字', () => expect(render('ACTIVE').text()).toBe('有效'))
  it('显示撤销状态文字', () => expect(render('REVOKED').text()).toBe('已撤销'))
  it('未知状态仍显示原值', () => expect(render('CUSTOM').text()).toBe('CUSTOM'))
})
