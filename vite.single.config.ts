import { defineConfig } from 'vite';
import { viteSingleFile } from 'vite-plugin-singlefile';

// すべての JS/CSS/アセットを 1 つの HTML に埋め込むビルド設定。
// 出力された dist-single/index.html は、サーバーなしで
// ダブルクリックするだけ(file://)で動く配布用ファイルになる。
export default defineConfig({
  base: './',
  plugins: [viteSingleFile()],
  build: {
    outDir: 'dist-single',
    // PDF ワーカーなどのアセットも data URI として埋め込む
    assetsInlineLimit: 100_000_000,
    chunkSizeWarningLimit: 10_000,
  },
});
