<script setup lang="ts">
import { onMounted } from 'vue'
import StatusIndicator from '@/components/StatusIndicator.vue'
import { useSystemStore } from '@/stores/system'
import IbtracsManager from '@/components/IbtracsManager.vue'
const system = useSystemStore()
onMounted(() => system.refresh())
</script>
<template>
  <section v-loading="system.loading" class="page-stack">
    <div class="page-heading"><div><h2>运行配置与数据源</h2><p>当前服务运行环境、本地存储位置与真实数据接入任务。</p></div></div>
    <el-alert v-if="system.error" :title="system.error" type="error" :closable="false" show-icon/>
    <el-card shadow="never" class="data-card"><template #header><strong>软件与服务</strong></template><el-descriptions :column="2" border><el-descriptions-item label="软件名称">{{system.info?.software_name??'未获取'}}</el-descriptions-item><el-descriptions-item label="品牌名称">{{system.info?.brand??'未获取'}}</el-descriptions-item><el-descriptions-item label="系统版本">{{system.info?.version??'未获取'}}</el-descriptions-item><el-descriptions-item label="后端状态"><StatusIndicator :active="system.backendOnline"/></el-descriptions-item><el-descriptions-item label="Python 版本">{{system.info?.python_version??'未获取'}}</el-descriptions-item><el-descriptions-item label="运行平台">{{system.info?.platform??'未获取'}}</el-descriptions-item><el-descriptions-item label="数据库路径" :span="2">{{system.info?.database_path??'未获取'}}</el-descriptions-item><el-descriptions-item label="数据根目录" :span="2">{{system.info?.data_root??'未获取'}}</el-descriptions-item></el-descriptions></el-card>
    <el-card shadow="never" class="data-card"><IbtracsManager /></el-card>
    <el-card shadow="never"><template #header><strong>配置说明</strong></template><p class="body-copy">服务参数可通过项目根目录的 <code>.env</code> 配置；首次使用可复制 <code>.env.example</code>。敏感配置不得提交。CMA 和 ERA5 尚未接入。</p></el-card>
  </section>
</template>
