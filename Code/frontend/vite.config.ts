import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],

  // Use relative paths so PyWebView can load assets via file:// protocol
  base: './',

  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        floating: resolve(__dirname, 'floating.html'),
      },
    },
  },
})
