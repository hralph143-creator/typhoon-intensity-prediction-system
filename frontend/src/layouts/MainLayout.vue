<script setup lang="ts">
import {Aim,DataAnalysis,DataLine,Document,Files,HomeFilled,InfoFilled,Menu as MenuIcon,Operation,Setting,TrendCharts} from '@element-plus/icons-vue'
import {computed,ref} from 'vue'
import {useRoute} from 'vue-router'
const route=useRoute(),collapsed=ref(false)
const pageTitle=computed(()=>String(route.meta.title??'系统首页'))
const activePath=computed(()=>route.path.startsWith('/history/')?'/history':route.path)
const items=[['/','系统首页',HomeFilled],['/history','历史台风数据',Files],['/wind-field','气象风场分析',DataAnalysis],['/training','模型训练',Operation],['/prediction','强度预测',Aim],['/evaluation','预测性能评估',TrendCharts],['/experiments','实验记录',DataLine],['/reports','科研分析报告',Document],['/settings','系统设置',Setting],['/about','关于系统',InfoFilled]] as const
</script>
<template><div class="app-shell"><aside class="sidebar" :class="{collapsed}"><div class="brand"><img class="brand-mark" src="/app-icon.png" alt="云浪智析图标"><div v-if="!collapsed" class="brand-text"><strong>云浪智析</strong><small>台风强度预测系统</small></div></div><el-menu :default-active="activePath" router :collapse="collapsed" class="nav-menu"><el-menu-item v-for="item in items" :key="item[0]" :index="item[0]"><el-icon><component :is="item[2]"/></el-icon><template #title>{{item[1]}}</template></el-menu-item></el-menu><div v-if="!collapsed" class="sidebar-foot">本地科研分析平台 · v0.10.0</div></aside><section class="content-shell"><header class="topbar"><button class="collapse-button" aria-label="切换导航栏" @click="collapsed=!collapsed"><el-icon><MenuIcon/></el-icon></button><h1>{{pageTitle}}</h1><span class="topbar-product">基于时空注意力的台风强度预测系统</span></header><main class="page-container"><RouterView/></main></section></div></template>
