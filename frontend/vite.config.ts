import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes("node_modules/react") || id.includes("node_modules/react-dom") || id.includes("node_modules/react-router-dom")) {
            return "vendor-react";
          }
          if (id.includes("node_modules/@tanstack/react-query") || id.includes("node_modules/@tanstack/react-query-persist-client")) {
            return "vendor-query";
          }
          if (id.includes("node_modules/lightweight-charts") || id.includes("node_modules/recharts")) {
            return "vendor-charts";
          }
          if (id.includes("node_modules/lucide-react") || id.includes("node_modules/sonner") || id.includes("node_modules/class-variance-authority") || id.includes("node_modules/clsx") || id.includes("node_modules/tailwind-merge")) {
            return "vendor-ui";
          }
          if (id.includes("node_modules/dockview")) {
            return "vendor-dockview";
          }
        },
      },
    },
  },
})
