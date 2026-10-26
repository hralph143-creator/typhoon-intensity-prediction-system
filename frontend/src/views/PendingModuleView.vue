<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Clock } from '@element-plus/icons-vue'
const route = useRoute()
const title = computed(() => String(route.meta.title ?? '业务模块'))
const description = computed(() => String(route.meta.description ?? '该模块尚未接入。'))
</script>
<template><section class="pending-panel"><el-icon :size="42"><Clock/></el-icon><h2>{{title}}</h2><p>{{description}}</p><el-tag type="info" effect="plain">该模块尚未接入</el-tag><div class="pending-note">为保证科研结果真实可信，本阶段不使用模拟数据填充页面。</div></section></template>
