<script setup lang="ts">
import {Aim,DataAnalysis,DataLine,Files,HomeFilled,InfoFilled,Menu as MenuIcon,Operation,Setting,TrendCharts} from '@element-plus/icons-vue'
import {computed,ref} from 'vue'
import {useRoute} from 'vue-router'
const route=useRoute(),collapsed=ref(false)
const pageTitle=computed(()=>String(route.meta.title??'系统首页'))
const activePath=computed(()=>route.path.startsWith('/history/')?'/history':route.path)
const items=[['/','系统首页',HomeFilled],['/history','历史台风数据',Files],['/wind-field','气象风场分析',DataAnalysis],['/training','模型训练',Operation],['/prediction','强度预测',Aim],['/evaluation','预测性能评估',TrendCharts],['/experiments','实验记录',DataLine],['/settings','系统设置',Setting],['/about','关于系统',InfoFilled]] as const
</script>
<template><div class="app-shell"><aside class="sidebar" :class="{collapsed}"><div class="brand"><div class="brand-mark">云</div><div v-if="!collapsed" class="brand-text"><strong>云浪智析</strong><span>台风强度预测系统</span></div></div><el-menu :default-active="activePath" router :collapse="collapsed" class="nav-menu"><el-menu-item v-for="item in items" :key="item[0]" :index="item[0]"><el-icon><component :is="item[2]"/></el-icon><template #title>{{item[1]}}</template></el-menu-item></el-menu><div v-if="!collapsed" class="phase-label">当前阶段：真实历史数据</div></aside><section class="content-shell"><header class="topbar"><button class="collapse-button" aria-label="切换导航栏" @click="collapsed=!collapsed"><el-icon><MenuIcon/></el-icon></button><div><h1>{{pageTitle}}</h1><p>基于时空注意力的台风强度预测系统</p></div><div class="research-badge">科研用途 · 非业务预警</div></header><main class="page-container"><RouterView/></main></section></div></template>
