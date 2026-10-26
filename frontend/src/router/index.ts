import { createRouter,createWebHistory } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'
import PendingModuleView from '@/views/PendingModuleView.vue'
const router = createRouter({
  history: createWebHistory(),
  routes: [{ path: '/', component: MainLayout, children: [
    { path: '', component: () => import('@/views/HomeView.vue'), meta: { title: '系统首页' } },
    { path: 'history', component: () => import('@/views/HistoryView.vue'), meta: { title: '历史台风数据' } },
    { path: 'history/:id', component: () => import('@/views/TyphoonDetailView.vue'), meta: { title: '台风详情' } },
    { path: 'wind-field', component: PendingModuleView, meta: { title: '气象风场分析', description: '尚未接入 ERA5 风场数据。' } },
    { path: 'training', component: PendingModuleView, meta: { title: '模型训练', description: '当前阶段未安装或训练预测模型。' } },
    { path: 'prediction', component: PendingModuleView, meta: { title: '强度预测', description: '需要真实数据与已验证模型后才能使用。' } },
    { path: 'evaluation', component: PendingModuleView, meta: { title: '预测性能评估', description: '目前没有真实实验结果可供评估。' } },
    { path: 'experiments', component: PendingModuleView, meta: { title: '实验记录', description: '实验管理将在模型开发阶段接入。' } },
    { path: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { title: '系统设置' } },
    { path: 'about', component: () => import('@/views/AboutView.vue'), meta: { title: '关于系统' } },
  ] }, { path: '/:pathMatch(.*)*', redirect: '/' }],
})
router.afterEach(to=>{document.title=`${String(to.meta.title??'系统')} · 云浪智析`})
export default router
