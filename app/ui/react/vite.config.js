import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // Dev uses absolute asset URLs; the production build uses relative URLs so the
  // bundle works both at /react (during migration) and / (final swap).
  base: command === 'build' ? './' : '/',
  build: {
    outDir: '../react-dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/mcp': {
        target: 'http://localhost:18329',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    include: ['src/**/*.{test,spec}.{js,jsx}'],
  },
}))
