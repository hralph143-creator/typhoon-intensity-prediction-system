// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TrainingView from './TrainingView.vue'
import PredictionView from './PredictionView.vue'
import EvaluationView from './EvaluationView.vue'
import { getAudit, getComparison, getComparisonDetail, getExperiments, getModels, getPredictionRecords, getSafnetInfo, getSafnetSamples, getSampleStatistics } from '@/api/ml'
import { getTyphoons } from '@/api/typhoons'

vi.mock('vue-router',()=>({useRoute:()=>({query:{}})}))
vi.mock('@/api/ml',()=>({getAudit:vi.fn(),getSampleStatistics:vi.fn(),getExperiments:vi.fn(),getExperiment:vi.fn(),createExperiment:vi.fn(),cancelExperiment:vi.fn(),getModels:vi.fn(),historicalPredict:vi.fn(),getComparison:vi.fn(),getComparisonDetail:vi.fn(),getPredictionRecords:vi.fn(),getSafnetInfo:vi.fn(),getSafnetSamples:vi.fn(),safnetPredict:vi.fn()}))
vi.mock('@/api/typhoons',()=>({getTyphoons:vi.fn(),getTrack:vi.fn()}))
vi.mock('@/components/DataChart.vue',()=>({default:{props:['label'],template:'<div class="chart">{{label}}</div>'}}))

beforeEach(()=>{
  vi.mocked(getAudit).mockResolvedValue({observation_count:23188,valid_cma_wind_count:19552,missing_cma_wind_count:3636,missing_cma_wind_ratio:.1568,special_cma_17_count:0,abnormal_wind_count:0,strict_sample_count:8048,extended_sample_count:15136,cma_iflag_count:{O:10513,P:9039,_:3636},track_type_count:{MAIN:21246},yearly_valid_cma_wind:{2024:1594}})
  vi.mocked(getSampleStatistics).mockResolvedValue({quality_profile:'strict',dataset_version:'v',total:8048,splits:{train:{sample_count:6117,event_count:233,years:[2014],wind_min:1,wind_max:2,wind_mean:1},validation:{sample_count:1209,event_count:49,years:[2022],wind_min:1,wind_max:2,wind_mean:1},test:{sample_count:722,event_count:28,years:[2024],wind_min:1,wind_max:2,wind_mean:1},no_sid_leakage:true}})
  vi.mocked(getExperiments).mockResolvedValue([]);vi.mocked(getModels).mockResolvedValue([]);vi.mocked(getComparison).mockResolvedValue([]);vi.mocked(getComparisonDetail).mockResolvedValue({items:[],formal_ranking_allowed:false});vi.mocked(getPredictionRecords).mockResolvedValue({items:[],total:0,page:1,page_size:20})
  vi.mocked(getSafnetInfo).mockResolvedValue({availability:{ready:false,total:0,splits:{train:0,validation:0,test:0}},parameters:{total:180000,trainable:180000},config:{time_features:1},device:'cpu',pipeline:[]});vi.mocked(getSafnetSamples).mockResolvedValue([])
  vi.mocked(getTyphoons).mockResolvedValue({items:[],total:0,page:1,page_size:100})
})

describe('第三阶段页面',()=>{
  it('训练页面展示真实审计和集合隔离',async()=>{const wrapper=mount(TrainingView,{global:{plugins:[ElementPlus]}});await flushPromises();expect(wrapper.text()).toContain('8,048');expect(wrapper.text()).toContain('训练 6117 / 233 个事件');expect(wrapper.text()).toContain('SID 交叉：无');wrapper.unmount()})
  it('无模型时预测页面明确提示',async()=>{const wrapper=mount(PredictionView,{global:{plugins:[ElementPlus]}});await flushPromises();expect(wrapper.text()).toContain('尚无训练成功并保存的模型');expect(wrapper.text()).toContain('历史回测预测');wrapper.unmount()})
  it('评估页面只呈现已保存结果入口',async()=>{const wrapper=mount(EvaluationView,{global:{plugins:[ElementPlus]}});await flushPromises();expect(wrapper.text()).toContain('测试集未参与训练');expect(wrapper.findAll('.chart')).toHaveLength(2);wrapper.unmount()})
  it('训练和预测页面明确控制 SAF-Net 无数据状态',async()=>{const training=mount(TrainingView,{global:{plugins:[ElementPlus]}});await flushPromises();expect(training.text()).toContain('SAF-Net 参数');expect(training.text()).toContain('180,000');training.unmount();const prediction=mount(PredictionView,{global:{plugins:[ElementPlus]}});await flushPromises();expect(prediction.text()).toContain('SAF-Net 尚未完成真实数据训练');prediction.unmount()})
})
