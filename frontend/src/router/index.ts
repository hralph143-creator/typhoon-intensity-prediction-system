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
    { path: 'training', component: () => import('@/views/TrainingView.vue'), meta: { title: '模型训练' } },
    { path: 'prediction', component: () => import('@/views/PredictionView.vue'), meta: { title: '强度预测' } },
    { path: 'evaluation', component: () => import('@/views/EvaluationView.vue'), meta: { title: '预测性能评估' } },
    { path: 'experiments', component: () => import('@/views/ExperimentsView.vue'), meta: { title: '实验记录' } },
    { path: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { title: '系统设置' } },
    { path: 'about', component: () => import('@/views/AboutView.vue'), meta: { title: '关于系统' } },
  ] }, { path: '/:pathMatch(.*)*', redirect: '/' }],
})
router.afterEach(to=>{document.title=`${String(to.meta.title??'系统')} · 云浪智析`})
export default router
