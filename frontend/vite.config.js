import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backendTarget = process.env.VITE_BACKEND_URL || 'http://127.0.0.1:5000'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/static/spa/' : '/',
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/static': {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../backend/static/spa',
    emptyOutDir: true,
    assetsDir: '.',
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        entryFileNames: 'app.js',
        chunkFileNames: 'chunk-[name]-[hash].js',
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return
          }
          if (id.includes('echarts')) {
            return 'vendor-echarts'
          }
          if (id.includes('leaflet')) {
            return 'vendor-leaflet'
          }
          if (id.includes('vue')) {
            return 'vendor-vue'
          }
          return 'vendor'
        },
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith('.css')) {
            return 'app.css'
          }
          return 'asset-[name]-[hash][extname]'
        },
      },
    },
  },
}))
