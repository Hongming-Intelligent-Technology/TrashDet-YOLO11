<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import L from 'leaflet'
import { getJson } from '../lib/api'
import { escapeHtml } from '../lib/escape'
import { focusMapToDenseRegion } from '../lib/mapFocus'
import { pushFlash } from '../stores/session'

let pieChart = null
let lineChart = null
let map = null
let actualPointLayer = null
let hotspotLayer = null
let hasAutoFocused = false
let mapInteracted = false
const forecastMeta = ref([])
const forecastHotspots = ref([])
const hotspotProbabilityRows = ref([])
const recommendationNotes = ref([])

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function riskColor(score) {
  if (score >= 80) return '#ef4444'
  if (score >= 60) return '#f97316'
  if (score >= 40) return '#facc15'
  return '#22c55e'
}

function clampProbability(value) {
  const numericValue = Number(value)
  if (!Number.isFinite(numericValue)) return 0
  return Math.max(0, Math.min(100, Math.round(numericValue)))
}

function buildHotspotProbabilityRows(hotspots) {
  const rows = asArray(hotspots)
  if (!rows.length) {
    return []
  }

  const maxPredictedCount = rows.reduce((accumulator, item) => {
    const predictedCount = Number(item?.predicted_count || 0)
    if (!Number.isFinite(predictedCount)) {
      return accumulator
    }
    return Math.max(accumulator, predictedCount)
  }, 0)

  return rows.slice(0, 6).map((item, index) => {
    const districtText = String(
      item?.district || item?.city || item?.town || item?.display_name || `热点 ${index + 1}`,
    ).split(',')[0].trim()
    const labelsText = asArray(item?.dominant_labels).join('、') || '未知垃圾'

    const riskScore = Number(item?.risk_score)
    let probability = 0
    if (Number.isFinite(riskScore) && riskScore > 0) {
      probability = clampProbability(riskScore)
    } else if (maxPredictedCount > 0) {
      probability = clampProbability((Number(item?.predicted_count || 0) / maxPredictedCount) * 100)
    }

    return {
      id: String(item?.grid_id || item?.rank || index + 1),
      district: districtText || `热点 ${index + 1}`,
      probability,
      labels: labelsText,
    }
  })
}

function updateForecastPanels(payload) {
  const summary = payload?.summary || {}
  forecastMeta.value = [
    { label: '分析网格', value: summary.cells_analyzed || 0 },
    { label: '历史任务', value: summary.tasks_used || 0 },
    { label: '检测目标', value: summary.detections_used || 0 },
  ]

  const hotspots = asArray(payload?.hotspots)
  forecastHotspots.value = hotspots.slice(0, 3).map((item) => {
    const riskScore = Number(item.risk_score || 0)
    return {
      rank: item.rank ?? '-',
      riskScore,
      predictedCount: item.predicted_count ?? '-',
      dominantLabels: asArray(item.dominant_labels).join('、') || '未知',
      displayName: item.display_name || '未知位置',
      reason: item.reason || '',
    }
  })

  recommendationNotes.value = asArray(payload?.recommendations)
    .map((item) => String(item ?? '').trim())
    .filter((item) => item)
}

async function loadStats() {
  try {
    const [summary, hotspots] = await Promise.all([
      getJson('/api/stats/summary'),
      getJson('/api/stats/hotspots'),
    ])

    pieChart.setOption({
      tooltip: {},
      series: [{ type: 'pie', radius: ['40%', '70%'], data: summary.pie_data || [], label: { color: '#2f5b53' } }],
    })

    lineChart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { type: 'scroll', top: 0, textStyle: { color: '#2f5b53' } },
      grid: { left: 48, right: 24, top: 54, bottom: 54 },
      xAxis: { type: 'category', data: summary.line_data?.labels || [], boundaryGap: false, axisLabel: { color: '#2f5b53' } },
      yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#2f5b53' } },
      series: asArray(summary.line_data?.series).map((item) => ({ name: item.name, type: 'line', smooth: true, data: item.values || [] })),
    })

    updateForecastPanels(hotspots)
    hotspotProbabilityRows.value = buildHotspotProbabilityRows(hotspots.hotspots)

    actualPointLayer.clearLayers()
    asArray(summary.locations).forEach((location) => {
      if (location.lat == null || location.lng == null) return
      L.marker([location.lat, location.lng], {
        icon: L.divIcon({ className: 'map-dot-icon', html: '<span class="map-dot"></span>', iconSize: [10, 10], iconAnchor: [5, 5] }),
      }).addTo(actualPointLayer).bindPopup(`<b>任务 ${escapeHtml(location.id)}</b><br>${escapeHtml(location.trash_types)}`)
    })

    hotspotLayer.clearLayers()
    asArray(hotspots.hotspots).forEach((item) => {
      if (item.center_lat == null || item.center_lng == null) return
      L.circleMarker([item.center_lat, item.center_lng], {
        radius: 10,
        color: riskColor(item.risk_score),
        fillColor: riskColor(item.risk_score),
        fillOpacity: 0.35,
      }).addTo(hotspotLayer).bindPopup(`TOP ${escapeHtml(item.rank)}<br>${escapeHtml(item.display_name || '未知位置')}`)
    })

    if (!mapInteracted && !hasAutoFocused) {
      const focusPoints = [
        ...asArray(summary.locations).map((item) => ({ lat: item.lat, lng: item.lng })),
        ...asArray(hotspots.hotspots).map((item) => ({
          lat: item.center_lat,
          lng: item.center_lng,
          weight: Number(item.predicted_count || item.risk_score || 1),
        })),
      ]
      hasAutoFocused = focusMapToDenseRegion(map, focusPoints, { gridSize: 0.28, maxZoom: 15, singlePointZoom: 14 })
    }
  } catch (error) {
    pushFlash(error.message || '统计数据加载失败', 'error')
  }
}

function onResize() {
  pieChart?.resize()
  lineChart?.resize()
  map?.invalidateSize()
}

onMounted(() => {
  pieChart = echarts.init(document.getElementById('pieChart'))
  lineChart = echarts.init(document.getElementById('lineChart'))
  map = L.map('statsMap').setView([30, 110], 5)
  actualPointLayer = L.layerGroup().addTo(map)
  hotspotLayer = L.layerGroup().addTo(map)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map)
  map.on('dragstart zoomstart', () => {
    mapInteracted = true
  })
  loadStats()
  window.setTimeout(() => map?.invalidateSize(), 500)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  pieChart?.dispose()
  lineChart?.dispose()
  map?.remove()
})
</script>

<template>
  <div class="panel page-panel">
    <div class="panel-title">数据分析</div>
    <div class="panel-body">
      <div class="stats-grid">
        <div class="stats-card">
          <div class="section-title section-title-sm">垃圾种类分布</div>
          <div id="pieChart" class="chart-fixed-260"></div>
        </div>
        <div class="stats-card">
          <div class="section-title section-title-sm">全部识别趋势</div>
          <div id="lineChart" class="chart-fixed-260"></div>
        </div>
        <div class="stats-card">
          <div class="section-title section-title-sm">未来 24 小时热点预测</div>
          <div class="hotspot-prob-list">
            <div v-for="item in hotspotProbabilityRows" :key="item.id" class="hotspot-prob-item">
              <div class="hotspot-prob-main">
                <span class="hotspot-prob-area">{{ item.district }}</span>
                <span class="hotspot-prob-rate">{{ item.probability }}%</span>
              </div>
              <div class="hotspot-prob-sub">垃圾类型：{{ item.labels }}</div>
            </div>
            <div v-if="!hotspotProbabilityRows.length" class="forecast-list-note">暂无热点预测数据</div>
          </div>
        </div>
        <div class="stats-card">
          <div class="section-title section-title-sm">巡检建议</div>
          <div class="forecast-meta">
            <div v-for="item in forecastMeta" :key="item.label" class="forecast-meta-item">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
          <div class="forecast-list">
            <div v-for="item in forecastHotspots" :key="`hotspot-${item.rank}`" class="forecast-list-item">
              <div class="forecast-list-head">
                <span class="forecast-rank">TOP {{ item.rank }}</span>
                <span class="forecast-risk" :style="{ background: riskColor(item.riskScore) }">风险 {{ item.riskScore
                }}</span>
              </div>
              <div class="forecast-list-main">预测目标数 {{ item.predictedCount }}，主导类型：{{ item.dominantLabels }}</div>
              <div class="forecast-list-sub">位置：{{ item.displayName }}</div>
              <div class="forecast-list-sub">{{ item.reason }}</div>
            </div>
            <div v-for="(item, index) in recommendationNotes" :key="`note-${index}`" class="forecast-list-note">{{ item
            }}</div>
            <div v-if="!forecastHotspots.length && !recommendationNotes.length" class="forecast-list-note">暂无巡检建议</div>
          </div>
        </div>
      </div>
      <div class="stats-map-wrap">
        <div class="section-title section-title-sm stats-map-title">实际点位与预测热点</div>
        <div id="statsMap" class="stats-map"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stats-card .section-title {
  color: #111827;
}

.forecast-meta-item span,
.forecast-meta-item strong {
  color: #111827;
}

.forecast-meta-item strong {
  font-weight: 800;
}

.hotspot-prob-list {
  margin-top: 8px;
  display: grid;
  gap: 8px;
}

.hotspot-prob-item {
  border-radius: 10px;
  border: 1px solid rgba(25, 84, 71, 0.22);
  background: #ffffff;
  padding: 10px;
}

.hotspot-prob-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.hotspot-prob-area {
  color: #111827;
  font-weight: 700;
}

.hotspot-prob-rate {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 2px 10px;
  color: #111827;
  font-size: 12px;
  font-weight: 800;
  background: rgba(141, 196, 176, 0.24);
}

.hotspot-prob-sub {
  margin-top: 6px;
  color: #1f2937;
  font-size: 13px;
}
</style>
