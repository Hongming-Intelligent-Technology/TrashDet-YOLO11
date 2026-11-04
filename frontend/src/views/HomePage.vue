<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import L from 'leaflet'
import { getJson } from '../lib/api'
import { escapeHtml } from '../lib/escape'
import { focusMapToDenseRegion } from '../lib/mapFocus'
import { pushFlash } from '../stores/session'

const robotList = ref([])
let chart = null
let map = null
let refreshTimer = null
let hasAutoFocused = false
let mapInteracted = false
const markers = {}
const taskMarkers = {}

function buildRobotPopup(robot) {
  const batteryText = robot.battery != null ? `${escapeHtml(robot.battery)}%` : ''
  return `<b>${escapeHtml(robot.name || '-')}</b><br>${escapeHtml(robot.device_id || '-')}<br>${escapeHtml(robot.status || '-')} ${batteryText}`
}

function renderTaskPopup(location) {
  const lat = Number(location.lat)
  const lng = Number(location.lng)
  const latText = Number.isFinite(lat) ? lat.toFixed(4) : '-'
  const lngText = Number.isFinite(lng) ? lng.toFixed(4) : '-'
  return `
    <div class="map-popup-card">
      <h4 class="map-popup-title">任务 #${escapeHtml(location.id)}</h4>
      <p class="map-popup-body"><b>识别结果:</b> <span class="map-popup-highlight">${escapeHtml(location.trash_types || '未检测到')}</span></p>
      <p class="map-popup-foot">坐标: ${latText}, ${lngText}</p>
    </div>
  `
}

function syncRobotMarkers(robots) {
  const activeIds = new Set()
  robots.forEach((robot) => {
    if (robot.lat == null || robot.lng == null || !map) {
      return
    }
    const id = String(robot.device_id || robot.id)
    activeIds.add(id)
    if (markers[id]) {
      markers[id].setLatLng([robot.lat, robot.lng])
      markers[id].setPopupContent(buildRobotPopup(robot))
      return
    }
    markers[id] = L.marker([robot.lat, robot.lng], {
      icon: L.divIcon({
        className: 'map-dot-icon',
        html: '<span class="map-dot map-dot-robot"></span>',
        iconSize: [14, 14],
        iconAnchor: [7, 7],
      }),
    }).addTo(map).bindPopup(buildRobotPopup(robot))
  })

  Object.keys(markers).forEach((id) => {
    if (activeIds.has(id)) {
      return
    }
    map.removeLayer(markers[id])
    delete markers[id]
  })
}

function syncTaskMarkers(locations) {
  const activeIds = new Set()
  locations.forEach((location) => {
    if (!map || location.lat == null || location.lng == null || location.id == null) {
      return
    }
    const id = String(location.id)
    activeIds.add(id)
    if (taskMarkers[id]) {
      taskMarkers[id].setLatLng([location.lat, location.lng])
      taskMarkers[id].setPopupContent(renderTaskPopup(location))
      return
    }
    taskMarkers[id] = L.marker([location.lat, location.lng], {
      icon: L.divIcon({
        className: 'map-dot-icon',
        html: '<span class="map-dot"></span>',
        iconSize: [14, 14],
        iconAnchor: [7, 7],
      }),
    }).addTo(map)
    taskMarkers[id].bindPopup(renderTaskPopup(location), { closeButton: false, offset: L.point(0, -15) })
    taskMarkers[id].on('mouseover', function onMouseOver() {
      this.openPopup()
    })
    taskMarkers[id].on('mouseout', function onMouseOut() {
      this.closePopup()
    })
  })

  Object.keys(taskMarkers).forEach((id) => {
    if (activeIds.has(id)) {
      return
    }
    map.removeLayer(taskMarkers[id])
    delete taskMarkers[id]
  })
}

function renderPieChart(data) {
  chart?.setOption({
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      data: data?.length ? data : [{ name: '暂无数据', value: 1 }],
      label: { color: '#2f5b53' },
      itemStyle: { borderRadius: 5 },
    }],
  })
}

async function loadDashboard() {
  try {
    const payload = await getJson('/api/stats/summary')
    robotList.value = payload.robot_list || []
    renderPieChart(payload.pie_data || [])
    syncRobotMarkers(payload.robot_list || [])
    syncTaskMarkers(payload.locations || [])

    if (!mapInteracted && !hasAutoFocused) {
      const focusPoints = [
        ...(payload.locations || []).map((item) => ({ lat: item.lat, lng: item.lng })),
        ...(payload.robot_list || []).map((item) => ({ lat: item.lat, lng: item.lng })),
      ]
      hasAutoFocused = focusMapToDenseRegion(map, focusPoints, { gridSize: 0.32, maxZoom: 15, singlePointZoom: 14 })
    }
  } catch (error) {
    pushFlash(error.message || '首页数据加载失败', 'error')
  }
}

onMounted(() => {
  chart = echarts.init(document.getElementById('trashTypeChart'))
  map = L.map('map', { zoomControl: false }).setView([30, 110], 5)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map)
  L.control.zoom({ position: 'topright' }).addTo(map)
  map.on('dragstart zoomstart', () => {
    mapInteracted = true
  })
  loadDashboard()
  refreshTimer = window.setInterval(loadDashboard, 3000)
  window.setTimeout(() => map?.invalidateSize(), 500)
  window.addEventListener('resize', onResize)
})

function onResize() {
  chart?.resize()
  map?.invalidateSize()
}

onBeforeUnmount(() => {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
  }
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  map?.remove()
})
</script>

<template>
  <div class="home-page">
    <div class="home-map-stage">
      <div id="map" class="home-map"></div>

      <div class="home-float-panel">
        <section class="panel home-overlay-panel">
          <div class="panel-title">垃圾种类环形图</div>
          <div class="home-overlay-body">
            <div id="trashTypeChart" class="home-donut-chart"></div>
          </div>
        </section>

        <section class="panel home-overlay-panel">
          <div class="panel-title">机器人在线状态</div>
          <div class="home-overlay-body home-table-body">
            <div class="home-status-summary">
              <span class="home-status-pill home-status-pill-online">在线 {{robotList.filter((robot) => robot.status ===
                'ONLINE').length }}</span>
              <span class="home-status-pill">总数 {{ robotList.length }}</span>
            </div>
            <div class="home-status-table-wrap">
              <table class="home-status-table">
                <thead>
                  <tr>
                    <th>设备ID</th>
                    <th>名称</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="robot in robotList" :key="robot.device_id || robot.name">
                    <td>{{ robot.device_id }}</td>
                    <td>{{ robot.name }}</td>
                    <td :class="robot.status === 'ONLINE' ? 'status-online-text' : 'status-offline-text'">
                      {{ robot.status === 'ONLINE' ? '● 在线' : '● 离线' }}
                    </td>
                  </tr>
                  <tr v-if="!robotList.length">
                    <td colspan="3" class="home-empty-row">载入中...</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.home-page {
  width: 100%;
  height: calc(100vh - 120px);
  min-height: 640px;
}

.home-map-stage {
  position: relative;
  width: 100%;
  height: 100%;
}

.home-map {
  width: 100%;
  height: 100%;
  border-radius: 12px;
  overflow: hidden;
}

.home-float-panel {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 500;
  width: min(420px, calc(100% - 24px));
  max-height: calc(100% - 24px);
  display: grid;
  gap: 10px;
  overflow: auto;
}

.home-overlay-panel {
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(10px);
}

.home-overlay-body {
  padding: 10px;
}

.home-donut-chart {
  width: 100%;
  height: 220px;
}

.home-table-body {
  display: grid;
  gap: 10px;
}

.home-status-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.home-status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(31, 142, 115, 0.1);
  color: #1d5f50;
  font-size: 12px;
  font-weight: 700;
}

.home-status-pill-online {
  background: rgba(31, 142, 115, 0.16);
  color: #0f7d5d;
}

.home-status-table-wrap {
  max-height: 260px;
  overflow: auto;
  border-radius: 10px;
  border: 1px solid rgba(36, 108, 91, 0.14);
}

.home-status-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 12px;
}

.home-status-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 9px 10px;
  text-align: left;
  background: rgba(240, 248, 243, 0.98);
  color: #1d554a;
  border-bottom: 1px solid rgba(36, 108, 91, 0.16);
}

.home-status-table tbody td {
  padding: 9px 10px;
  color: #315950;
  border-bottom: 1px solid rgba(36, 108, 91, 0.08);
}

.home-status-table tbody tr:hover {
  background: rgba(47, 133, 111, 0.07);
}

.home-empty-row {
  text-align: center;
  color: #5a726d;
}

@media (max-width: 900px) {
  .home-page {
    height: calc(100vh - 112px);
    min-height: 560px;
  }

  .home-float-panel {
    width: min(360px, calc(100% - 20px));
    top: 10px;
    left: 10px;
    max-height: calc(100% - 20px);
  }

  .home-donut-chart {
    height: 180px;
  }

  .home-status-table-wrap {
    max-height: 220px;
  }
}

@media (max-width: 640px) {
  .home-page {
    height: calc(100vh - 104px);
    min-height: 520px;
  }

  .home-float-panel {
    width: calc(100% - 16px);
    top: 8px;
    left: 8px;
    max-height: calc(100% - 16px);
  }

  .home-overlay-body {
    padding: 8px;
  }

  .home-donut-chart {
    height: 160px;
  }

  .home-status-table {
    font-size: 11px;
  }
}
</style>
