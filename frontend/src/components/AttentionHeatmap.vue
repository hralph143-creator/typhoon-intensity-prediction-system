<script setup lang="ts">
import {nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
const props=defineProps<{matrix:number[][];label:string}>();const canvas=ref<HTMLCanvasElement>();let observer:ResizeObserver|undefined
function draw(){const element=canvas.value;if(!element||!props.matrix.length)return;const box=element.getBoundingClientRect(),dpr=devicePixelRatio||1;element.width=box.width*dpr;element.height=box.height*dpr;const context=element.getContext('2d')!;context.scale(dpr,dpr);const rows=props.matrix.length,columns=props.matrix[0].length,values=props.matrix.flat(),low=Math.min(...values),high=Math.max(...values),width=box.width/columns,height=box.height/rows
  props.matrix.forEach((row,y)=>row.forEach((value,x)=>{const t=(value-low)/Math.max(high-low,1e-8);context.fillStyle=`hsl(${220-210*t} 76% ${48+8*t}%)`;context.fillRect(x*width,y*height,width+1,height+1)}))
}
watch(()=>props.matrix,()=>nextTick(draw),{deep:true});onMounted(()=>{observer=new ResizeObserver(draw);observer.observe(canvas.value!);draw()});onBeforeUnmount(()=>observer?.disconnect())
</script>
<template><canvas ref="canvas" class="attention-map" role="img" :aria-label="label"/></template>
<style scoped>.attention-map{width:100%;aspect-ratio:1;display:block;background:#eef2f5;border-radius:4px}</style>
