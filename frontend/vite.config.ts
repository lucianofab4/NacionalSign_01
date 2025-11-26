import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from 'tailwindcss';
import autoprefixer from 'autoprefixer';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  return {
    plugins: [react()],
    server: {
      port: env.VITE_PORT ? Number(env.VITE_PORT) : 5173,
    },
    css: {
      postcss: {
        plugins: [
          // Inline PostCSS config to avoid reading external JSON configs
          tailwindcss(),
          autoprefixer(),
        ],
      },
    },
    build: {
      outDir: 'dist',
    },
  };
});
