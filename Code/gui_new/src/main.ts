import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './assets/global.css'
import App from './App.vue'
import { vRipple } from './directives/ripple'

// Apply system dark mode preference on load
if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
  document.documentElement.classList.add('dark')
}

const app = createApp(App)
app.use(createPinia())
app.directive('ripple', vRipple)
app.mount('#app')
