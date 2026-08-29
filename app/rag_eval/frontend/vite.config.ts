import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  base: "/static/rag_eval_app/",
  build: {
    outDir: "../../static/rag_eval_app",
    emptyOutDir: true,
  },
});
