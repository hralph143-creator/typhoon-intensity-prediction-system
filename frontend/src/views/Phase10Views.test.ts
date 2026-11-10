// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import PredictionView from './PredictionView.vue'
import EvaluationView from './EvaluationView.vue'

const point=(mae:number)=>({sample_count:20,mae,rmse:mae+1,bias:-1})
const probability={by_horizon:{'6':{coverage_p10_p90:.4,mean_interval_width:7,pinball_loss:2},'12':{coverage_p10_p90:.65,mean_interval_width:12,pinball_loss:2},'18':{coverage_p10_p90:.65,mean_interval_width:12,pinball_loss:2},'24':{coverage_p10_p90:.65,mean_interval_width:14,pinball_loss:2}}}
const summary={available:true,dataset_version:'multi-horizon-test',baselines:Object.fromEntries(['persistence','ridge','gru'].map((name,index)=>[name,{test:{by_horizon:Object.fromEntries(['6','12','18','24'].map((h,i)=>[h,point(index+i+1)]))}}])),selected_candidate:{test:{by_horizon:Object.fromEntries(['6','12','18','24'].map((h,i)=>[h,point(i+5)])),probability}},selected_ablations:[{variant:'full_safnet',seed:42,parameters:100,best_epoch:3,validation:{overall:{mae:1}},test:{overall:{mae:5}}}]}

vi.mock('vue-router',()=>({useRoute:()=>({query:{}})}))
vi.mock('@/api/ml',()=>({getModels:vi.fn(async()=>[]),getSafnetInfo:vi.fn(async()=>({})),getSafnetSamples:vi.fn(async()=>[]),getPhase10Summary:vi.fn(async()=>summary),getPhase10Samples:vi.fn(async()=>[{id:'s1',sid:'2024001N',forecast_time:'2024-01-01T00:00:00Z'}]),phase10Predict:vi.fn(async()=>({sid:'2024001N',horizons:[6,12,18,24],actual:[20,21,22,23],p10:[17,18,19,20],p50:[20,20,21,22],p90:[24,25,26,27]})),getComparisonDetail:vi.fn(async()=>({items:[],formal_ranking_allowed:false})),getCommonTestComparison:vi.fn(async()=>({items:[],reason:'测试集未参与训练'})),getPredictionRecords:vi.fn(async()=>({items:[],total:0})),getExperiment:vi.fn(),historicalPredict:vi.fn(),safnetPredict:vi.fn()}))
vi.mock('@/api/typhoons',()=>({getTyphoons:vi.fn(async()=>({items:[]})),getTrack:vi.fn(),getTyphoon:vi.fn()}))
vi.mock('@/components/DataChart.vue',()=>({default:{props:['label'],template:'<div class="chart">{{label}}</div>'}}))
vi.mock('@/components/AttentionHeatmap.vue',()=>({default:{template:'<div />'}}))

describe('第十阶段页面',()=>{
  it('执行多时效推理并渲染预测区间和导出入口',async()=>{const wrapper=mount(PredictionView,{global:{plugins:[ElementPlus]}});await flushPromises();expect(wrapper.text()).toContain('多时效概率预测');const button=wrapper.findAll('button').find(x=>x.text().includes('预测 6 / 12'));await button?.trigger('click');await flushPromises();expect(wrapper.text()).toContain('P10');expect(wrapper.text()).toContain('P90');expect(wrapper.text()).toContain('导出图表 PNG');wrapper.unmount()})
  it('显示分时效指标、区间可靠性和消融筛选结果',async()=>{const wrapper=mount(EvaluationView,{global:{plugins:[ElementPlus]}});await flushPromises();expect(wrapper.text()).toContain('第十阶段结论');expect(wrapper.text()).toContain('覆盖率 40.0%');expect(wrapper.text()).toContain('full_safnet');expect(wrapper.findAll('.chart').length).toBeGreaterThanOrEqual(3);wrapper.unmount()})
})
