// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import HistoryView from './HistoryView.vue'
import { getStatistics, getTyphoons } from '@/api/typhoons'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api/typhoons', () => ({ getTyphoons: vi.fn(), getStatistics: vi.fn() }))
vi.mock('@/components/IbtracsManager.vue', () => ({ default: { template: '<div>导入管理</div>' } }))
afterEach(() => vi.clearAllMocks())

describe('历史档案页面', () => {
  it('空数据库显示真实空状态', async () => {
    vi.mocked(getTyphoons).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
    vi.mocked(getStatistics).mockResolvedValue({ typhoon_count: 0, observation_count: 0, main_observation_count: 0, years: [], yearly: [], missing_cma_wind_count: 0, last_import_at: null, latest_job: null })
    const wrapper = mount(HistoryView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('暂无符合条件的历史台风')
    expect(getTyphoons).toHaveBeenCalledWith(expect.objectContaining({ page: 1, page_size: 20, source: 'ibtracs' }))
    wrapper.unmount()
  })
  it('查询时将名称筛选发送至后端并从第一页开始', async () => {
    vi.mocked(getTyphoons).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
    vi.mocked(getStatistics).mockResolvedValue({ typhoon_count: 0, observation_count: 0, main_observation_count: 0, years: [], yearly: [], missing_cma_wind_count: 0, last_import_at: null, latest_job: null })
    const wrapper = mount(HistoryView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await wrapper.find('input[placeholder="如 HAIYAN"]').setValue('  RAMMASUN ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(getTyphoons).toHaveBeenLastCalledWith(expect.objectContaining({ name: 'RAMMASUN', page: 1 }))
    wrapper.unmount()
  })
  it('重置之后勾选临时轨迹发送 include_spurs=true，再取消发送 false', async () => {
    vi.mocked(getTyphoons).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
    vi.mocked(getStatistics).mockResolvedValue({ typhoon_count: 0, observation_count: 0, main_observation_count: 0, years: [], yearly: [], missing_cma_wind_count: 0, last_import_at: null, latest_job: null })
    const wrapper = mount(HistoryView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const reset = wrapper.findAll('button').find(button => button.text() === '重置')!
    await reset.trigger('click')
    await flushPromises()
    const checkbox = wrapper.get('input[type="checkbox"]')
    await checkbox.setValue(true)
    await flushPromises()
    expect(getTyphoons).toHaveBeenLastCalledWith(expect.objectContaining({ include_spurs: true, page: 1 }))
    await checkbox.setValue(false)
    await flushPromises()
    expect(getTyphoons).toHaveBeenLastCalledWith(expect.objectContaining({ include_spurs: false, page: 1 }))
    wrapper.unmount()
  })
})
