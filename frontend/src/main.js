import { createApp } from 'vue'
import 'leaflet/dist/leaflet.css'
import './app.css'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(router)
app.mount('#app')
