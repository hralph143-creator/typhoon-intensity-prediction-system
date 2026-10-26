// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import TyphoonDetailView from './TyphoonDetailView.vue'
import { getTrack, getTyphoon } from '@/api/typhoons'
import type { Observation, TyphoonDetail } from '@/types/typhoon'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { id: '1' } }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api/typhoons', () => ({ getTrack: vi.fn(), getTyphoon: vi.fn() }))
vi.mock('@/components/TyphoonMap.vue', () => ({ default: { props: ['points', 'selectedIndex'], emits: ['select'], template: '<div data-testid="map"><span>{{selectedIndex}}</span><button @click="$emit(\'select\', 1)">选择第二个地图点</button></div>' } }))
vi.mock('@/components/DataChart.vue', () => ({ default: { props: ['option', 'selectedIndex'], emits: ['select'], template: '<div data-testid="chart"><span>{{selectedIndex}}</span><button @click="$emit(\'select\', 0)">选择第一个曲线点</button></div>' } }))
const detail: TyphoonDetail = { id: 1, source: 'ibtracs', sid: 'ISOLATED_TEST_SID', season: 2020, number: 1, name: '隔离测试样例', first_observation: '2020-01-01T00:00:00Z', last_observation: '2020-01-01T03:00:00Z', observation_count: 2, maximum_wind: 30, minimum_pressure: 980, maximum_category: 3, source_files: [], track_types: ['MAIN'] }
const points: Observation[] = [0, 1].map((index) => ({ id: index + 1, observation_time: `2020-01-01T0${index * 3}:00:00Z`, latitude: 15 + index, longitude: 130 + index, basin: 'WP', track_type: 'MAIN', cma_wind: index ? null : 50, cma_wind_ms: index ? null : 25.7, cma_pressure: 990 - index * 10, cma_category: 3, wmo_wind_ms: null, wmo_pressure: null, wmo_agency: null, usa_wind_ms: 30, tokyo_wind_ms: 25, quality_flags: index ? ['missing_cma_wind'] : [], source_file_id: 1 }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getTyphoon).mockResolvedValue(detail)
  vi.mocked(getTrack).mockResolvedValue({ items: points, total: points.length, track_type: 'MAIN' })
})
describe('详情联动', () => {
  it('地图点击同步选择曲线和观测时间，曲线点击同步回地图', async () => {
    const wrapper = mount(TyphoonDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await wrapper.get('[data-testid="map"] button').trigger('click')
    expect(wrapper.get('[data-testid="chart"] span').text()).toBe('1')
    expect(wrapper.get('.selected-observation').text()).toContain('2020-01-01 03:00:00 UTC')
    expect(wrapper.get('.selected-observation').text()).toContain('— m/s')
    await wrapper.get('[data-testid="chart"] button').trigger('click')
    expect(wrapper.get('[data-testid="map"] span').text()).toBe('0')
    expect(wrapper.get('.selected-observation').text()).toContain('2020-01-01 00:00:00 UTC')
    wrapper.unmount()
  })
  it('下一时次按真实观测序列前进而不假定六小时间隔', async () => {
    const wrapper = mount(TyphoonDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    const next = wrapper.findAll('button').find(button => button.text() === '下一时次')!
    await next.trigger('click')
    expect(wrapper.get('.selected-observation').text()).toContain('03:00:00 UTC')
    expect(wrapper.get('[data-testid="map"] span').text()).toBe('1')
    wrapper.unmount()
  })
  it('没有轨迹时显示缺数据提示，不绘制虚假坐标和曲线', async () => {
    vi.mocked(getTrack).mockResolvedValue({ items: [], total: 0, track_type: 'MAIN' })
    const wrapper = mount(TyphoonDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('该轨迹类型暂无有效观测点')
    expect(wrapper.find('[data-testid="map"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="chart"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
