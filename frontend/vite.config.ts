import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/leaflet') || id.includes('node_modules/react-leaflet')) return 'map-vendor'
          if (id.includes('node_modules/recharts') || id.includes('node_modules/d3-')) return 'chart-vendor'
          if (id.includes('node_modules/react/') || id.includes('node_modules/react-dom/')) return 'react-vendor'
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    proxy: { '/api': 'http://localhost:8000' },
  },
})
