<script setup lang="ts">
defineProps<{ active: boolean; activeText?: string; inactiveText?: string }>()
</script>
<template><span class="status-indicator" :class="active?'active':'inactive'"><i/>{{active?(activeText??'正常'):(inactiveText??'未接入')}}</span></template>
