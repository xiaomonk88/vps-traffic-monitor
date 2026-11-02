import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({ plugins: [vue()], server: { proxy: Object.fromEntries(['/api', '/healthz', '/downloads', '/install.sh'].map(path => [path, { target: 'http://127.0.0.1:8080', changeOrigin: false }])) }, build: { sourcemap: false } })
