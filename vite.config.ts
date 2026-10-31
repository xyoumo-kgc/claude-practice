import { defineConfig } from 'vite';

export default defineConfig({
  // GitHub Pages のサブパス (/claude-practice/) でも動くように相対パスで出力する
  base: './',
});
