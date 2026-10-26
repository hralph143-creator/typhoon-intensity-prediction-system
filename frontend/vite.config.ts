import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL('..', import.meta.url)), '')
  return {
    plugins: [vue()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      port: 5173, strictPort: true,
      proxy: { '/api': { target: process.env.VITE_BACKEND_TARGET || `http://127.0.0.1:${env.APP_PORT || '8000'}`, changeOrigin: true } },
    },
    build: { rollupOptions: { output: { manualChunks: { charts: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/renderers'], map: ['leaflet'], ui: ['element-plus'] } } } },
  }
})
