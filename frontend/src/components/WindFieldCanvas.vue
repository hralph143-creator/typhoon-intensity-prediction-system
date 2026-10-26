<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
const props=defineProps<{u:number[][];v:number[][];label:string;scaleMin:number;scaleMax:number}>()
const canvas=ref<HTMLCanvasElement>();let observer:ResizeObserver|undefined
const speed=computed(()=>props.u.map((row,y)=>row.map((value,x)=>Math.hypot(value,props.v[y][x]))))
function color(value:number){const t=Math.max(0,Math.min(1,(value-props.scaleMin)/Math.max(.001,props.scaleMax-props.scaleMin)));const hue=210-190*t;return `hsl(${hue} 74% ${47+8*t}%)`}
function draw(){const el=canvas.value;if(!el)return;const box=el.getBoundingClientRect(),dpr=devicePixelRatio||1;el.width=box.width*dpr;el.height=box.height*dpr;const c=el.getContext('2d')!;c.scale(dpr,dpr);const w=box.width/31,h=box.height/31
  speed.value.forEach((row,y)=>row.forEach((value,x)=>{c.fillStyle=color(value);c.fillRect(x*w,(30-y)*h,w+1,h+1)}))
  c.strokeStyle='rgba(255,255,255,.85)';c.fillStyle=c.strokeStyle;c.lineWidth=1
  for(let y=2;y<31;y+=4)for(let x=2;x<31;x+=4){const u=props.u[y][x],v=props.v[y][x],m=Math.hypot(u,v)||1,len=Math.min(w*1.8,4+m*.32),cx=(x+.5)*w,cy=(30-y+.5)*h,dx=u/m*len,dy=-v/m*len;c.beginPath();c.moveTo(cx-dx/2,cy-dy/2);c.lineTo(cx+dx/2,cy+dy/2);c.stroke();const a=Math.atan2(dy,dx);c.beginPath();c.moveTo(cx+dx/2,cy+dy/2);c.lineTo(cx+dx/2-3*Math.cos(a-.55),cy+dy/2-3*Math.sin(a-.55));c.lineTo(cx+dx/2-3*Math.cos(a+.55),cy+dy/2-3*Math.sin(a+.55));c.fill()}
}
watch(()=>[props.u,props.v,props.scaleMin,props.scaleMax],()=>nextTick(draw),{deep:true});onMounted(()=>{observer=new ResizeObserver(draw);observer.observe(canvas.value!);draw()});onBeforeUnmount(()=>observer?.disconnect())
</script>
<template><canvas ref="canvas" class="wind-canvas" role="img" :aria-label="label"/></template>
<style scoped>.wind-canvas{display:block;width:100%;aspect-ratio:1;background:#e8eef3;border-radius:4px}</style>
