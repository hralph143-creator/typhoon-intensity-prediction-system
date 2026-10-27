// @vitest-environment jsdom
import {flushPromises,mount} from '@vue/test-utils'
import {beforeEach,describe,expect,it,vi} from 'vitest'
import WindFieldView from './WindFieldView.vue'
const api=vi.hoisted(()=>({status:vi.fn(),publicSample:vi.fn(),plans:vi.fn(),jobs:vi.fn(),files:vi.fn(),statistics:vi.fn(),build:vi.fn(),test:vi.fn(),importFile:vi.fn(),createJob:vi.fn(),cancelJob:vi.fn(),retryJob:vi.fn()}))
vi.mock('@/api/era5',()=>({era5Api:api}))
describe('WindFieldView',()=>{beforeEach(()=>{api.status.mockResolvedValue({configured:false,message:'未配置',disk_budget_gb:20});api.plans.mockResolvedValue([]);api.jobs.mockResolvedValue([]);api.files.mockResolvedValue([]);api.statistics.mockResolvedValue({era5_files:0,wind_fields:0,spatiotemporal_samples:0,splits:{}})})
it('shows truthful empty and public access state',async()=>{const wrapper=mount(WindFieldView,{global:{stubs:{'el-card':{template:'<div><slot/></div>'},'el-tabs':{template:'<div><slot/></div>'},'el-tab-pane':{template:'<section><slot/></section>'},'el-button':true,'el-alert':true,'el-table':true,'el-table-column':true,'el-collapse':true,'el-collapse-item':true,'el-empty':true},directives:{loading:()=>{}}}});await flushPromises();expect(wrapper.text()).toContain('待接入');expect(wrapper.text()).toContain('四时次样本');expect(api.statistics).toHaveBeenCalled()})})
