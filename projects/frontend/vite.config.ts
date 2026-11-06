import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const frontendDirectory = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  base: '/static/projects/home/build/',
  plugins: [react()],
  build: {
    outDir: path.resolve(frontendDirectory, '../static/projects/home/build'),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(frontendDirectory, 'src/main.tsx'),
      output: {
        entryFileNames: 'home.js',
        chunkFileNames: '[name].js',
        assetFileNames: 'home[extname]',
      },
    },
  },
})