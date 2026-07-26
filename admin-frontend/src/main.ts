import { createApp } from 'vue'
import {
  ElAlert,
  ElButton,
  ElDrawer,
  ElInputNumber,
  ElLoading,
  ElOption,
  ElSelect,
  ElSkeleton,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import { router } from './router'
import './styles.css'

const app = createApp(App)
for (const plugin of [
  ElAlert,
  ElButton,
  ElDrawer,
  ElInputNumber,
  ElLoading,
  ElOption,
  ElSelect,
  ElSkeleton,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
]) {
  app.use(plugin)
}
app.use(router).mount('#app')
