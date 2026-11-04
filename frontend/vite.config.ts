import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backendTarget = process.env.VITE_BACKEND_URL || 'http://127.0.0.1:5000'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/static/spa/' : '/',
  plugins: [react()],
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
    // Each lazy-loaded page ships its own CSS; the entry CSS stays at app.css for spa.html.
    cssCodeSplit: true,
    // vendor-echarts (~530 kB, only pie + line charts registered) is loaded lazily by the two chart pages.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        entryFileNames: 'app.js',
        chunkFileNames: 'chunk-[name]-[hash].js',
        manualChunks(id: string) {
          // CSS from node_modules (e.g. leaflet.css) is bundled into the CSS output. Assigning it
          // to a JS vendor chunk would make the entry import that whole chunk just for the CSS.
          if (!id.includes('node_modules') || id.endsWith('.css')) {
            return
          }
          if (id.includes('echarts') || id.includes('zrender')) {
            return 'vendor-echarts'
          }
          if (id.includes('leaflet')) {
            return 'vendor-leaflet'
          }
          if (id.includes('react') || id.includes('scheduler')) {
            return 'vendor-react'
          }
          return 'vendor'
        },
        assetFileNames: (assetInfo) => {
          const name = assetInfo.names?.[0] ?? ''
          if (name.endsWith('.css')) {
            return name === 'index.css' ? 'app.css' : 'chunk-[name]-[hash].css'
          }
          return 'asset-[name]-[hash][extname]'
        },
      },
    },
  },
}))
