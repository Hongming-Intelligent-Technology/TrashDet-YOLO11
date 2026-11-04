import { useEffect, useRef, useState } from 'react'
import * as echarts from '../lib/echarts'
import L from 'leaflet'
import { errorMessage, getJson } from '../lib/api'
import { escapeHtml } from '../lib/escape'
import { focusMapToDenseRegion } from '../lib/mapFocus'
import { pushFlash } from '../stores/session'
import type { TaskLocation } from '../types'
import './StatsPage.css'

interface SummaryResponse {
  pie_data?: Array<{ name: string; value: number }>
  line_data?: { labels?: string[]; series?: Array<{ name: string; values?: number[] }> }
  locations?: TaskLocation[]
}

interface Hotspot {
  grid_id?: string
  rank?: number
  risk_score?: number
  predicted_count?: number
  dominant_labels?: string[]
  display_name?: string
  district?: string
  city?: string
  town?: string
  reason?: string
  center_lat?: number | null
  center_lng?: number | null
}

interface HotspotsResponse {
  summary?: { cells_analyzed?: number; tasks_used?: number; detections_used?: number }
  hotspots?: Hotspot[]
  recommendations?: unknown[]
}

interface ProbabilityRow {
  id: string
  district: string
  probability: number
  labels: string
}

interface ForecastHotspot {
  rank: number | string
  riskScore: number
  predictedCount: number | string
  dominantLabels: string
  displayName: string
  reason: string
}

function asArray<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : []
}

function riskColor(score: unknown) {
  const value = Number(score)
  if (value >= 80) return '#ef4444'
  if (value >= 60) return '#f97316'
  if (value >= 40) return '#facc15'
  return '#22c55e'
}

function clampProbability(value: unknown) {
  const numericValue = Number(value)
  if (!Number.isFinite(numericValue)) return 0
  return Math.max(0, Math.min(100, Math.round(numericValue)))
}

function buildHotspotProbabilityRows(hotspots: Hotspot[] | undefined): ProbabilityRow[] {
  const rows = asArray(hotspots)
  if (!rows.length) {
    return []
  }

  const maxPredictedCount = rows.reduce((accumulator, item) => {
    const predictedCount = Number(item?.predicted_count || 0)
    return Number.isFinite(predictedCount) ? Math.max(accumulator, predictedCount) : accumulator
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

export default function StatsPage() {
  const pieElRef = useRef<HTMLDivElement>(null)
  const lineElRef = useRef<HTMLDivElement>(null)
  const mapElRef = useRef<HTMLDivElement>(null)

  const [forecastMeta, setForecastMeta] = useState<Array<{ label: string; value: number }>>([])
  const [forecastHotspots, setForecastHotspots] = useState<ForecastHotspot[]>([])
  const [hotspotProbabilityRows, setHotspotProbabilityRows] = useState<ProbabilityRow[]>([])
  const [recommendationNotes, setRecommendationNotes] = useState<string[]>([])

  useEffect(() => {
    const pieChart = echarts.init(pieElRef.current!)
    const lineChart = echarts.init(lineElRef.current!)
    const map = L.map(mapElRef.current!).setView([30, 110], 5)
    const actualPointLayer = L.layerGroup().addTo(map)
    const hotspotLayer = L.layerGroup().addTo(map)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map)

    let mapInteracted = false
    let disposed = false
    map.on('dragstart zoomstart', () => {
      mapInteracted = true
    })

    function updateForecastPanels(payload: HotspotsResponse) {
      const summary = payload?.summary || {}
      setForecastMeta([
        { label: '分析网格', value: summary.cells_analyzed || 0 },
        { label: '历史任务', value: summary.tasks_used || 0 },
        { label: '检测目标', value: summary.detections_used || 0 },
      ])

      setForecastHotspots(asArray(payload?.hotspots).slice(0, 3).map((item) => ({
        rank: item.rank ?? '-',
        riskScore: Number(item.risk_score || 0),
        predictedCount: item.predicted_count ?? '-',
        dominantLabels: asArray(item.dominant_labels).join('、') || '未知',
        displayName: item.display_name || '未知位置',
        reason: item.reason || '',
      })))

      setRecommendationNotes(
        asArray(payload?.recommendations)
          .map((item) => String(item ?? '').trim())
          .filter((item) => item),
      )
    }

    async function loadStats() {
      try {
        const [summary, hotspots] = await Promise.all([
          getJson<SummaryResponse>('/api/stats/summary'),
          getJson<HotspotsResponse>('/api/stats/hotspots'),
        ])
        if (disposed) {
          return
        }

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
        setHotspotProbabilityRows(buildHotspotProbabilityRows(hotspots.hotspots))

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

        if (!mapInteracted) {
          const focusPoints = [
            ...asArray(summary.locations).map((item) => ({ lat: item.lat, lng: item.lng })),
            ...asArray(hotspots.hotspots).map((item) => ({
              lat: item.center_lat,
              lng: item.center_lng,
              weight: Number(item.predicted_count || item.risk_score || 1),
            })),
          ]
          focusMapToDenseRegion(map, focusPoints, { gridSize: 0.28, maxZoom: 15, singlePointZoom: 14 })
        }
      } catch (error) {
        if (!disposed) {
          pushFlash(errorMessage(error, '统计数据加载失败'), 'error')
        }
      }
    }

    function onResize() {
      pieChart.resize()
      lineChart.resize()
      map.invalidateSize()
    }

    loadStats()
    const sizeTimer = window.setTimeout(() => map.invalidateSize(), 500)
    window.addEventListener('resize', onResize)

    return () => {
      disposed = true
      window.clearTimeout(sizeTimer)
      window.removeEventListener('resize', onResize)
      pieChart.dispose()
      lineChart.dispose()
      map.remove()
    }
  }, [])

  return (
    <div className="scope-stats panel page-panel">
      <div className="panel-title">数据分析</div>
      <div className="panel-body">
        <div className="stats-grid">
          <div className="stats-card">
            <div className="section-title section-title-sm">垃圾种类分布</div>
            <div id="pieChart" ref={pieElRef} className="chart-fixed-260"></div>
          </div>
          <div className="stats-card">
            <div className="section-title section-title-sm">全部识别趋势</div>
            <div id="lineChart" ref={lineElRef} className="chart-fixed-260"></div>
          </div>
          <div className="stats-card">
            <div className="section-title section-title-sm">未来 24 小时热点预测</div>
            <div className="hotspot-prob-list">
              {hotspotProbabilityRows.map((item) => (
                <div key={item.id} className="hotspot-prob-item">
                  <div className="hotspot-prob-main">
                    <span className="hotspot-prob-area">{item.district}</span>
                    <span className="hotspot-prob-rate">{item.probability}%</span>
                  </div>
                  <div className="hotspot-prob-sub">垃圾类型：{item.labels}</div>
                </div>
              ))}
              {!hotspotProbabilityRows.length && <div className="forecast-list-note">暂无热点预测数据</div>}
            </div>
          </div>
          <div className="stats-card">
            <div className="section-title section-title-sm">巡检建议</div>
            <div className="forecast-meta">
              {forecastMeta.map((item) => (
                <div key={item.label} className="forecast-meta-item">
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>
            <div className="forecast-list">
              {forecastHotspots.map((item) => (
                <div key={`hotspot-${item.rank}`} className="forecast-list-item">
                  <div className="forecast-list-head">
                    <span className="forecast-rank">TOP {item.rank}</span>
                    <span className="forecast-risk" style={{ background: riskColor(item.riskScore) }}>风险 {item.riskScore}</span>
                  </div>
                  <div className="forecast-list-main">预测目标数 {item.predictedCount}，主导类型：{item.dominantLabels}</div>
                  <div className="forecast-list-sub">位置：{item.displayName}</div>
                  <div className="forecast-list-sub">{item.reason}</div>
                </div>
              ))}
              {recommendationNotes.map((item, index) => (
                <div key={`note-${index}`} className="forecast-list-note">{item}</div>
              ))}
              {!forecastHotspots.length && !recommendationNotes.length && (
                <div className="forecast-list-note">暂无巡检建议</div>
              )}
            </div>
          </div>
        </div>
        <div className="stats-map-wrap">
          <div className="section-title section-title-sm stats-map-title">实际点位与预测热点</div>
          <div id="statsMap" ref={mapElRef} className="stats-map"></div>
        </div>
      </div>
    </div>
  )
}
