import { useEffect, useRef, useState } from 'react'
import * as echarts from '../lib/echarts'
import L from 'leaflet'
import { errorMessage, getJson } from '../lib/api'
import { escapeHtml } from '../lib/escape'
import { focusMapToDenseRegion } from '../lib/mapFocus'
import { pollWhileVisible } from '../lib/polling'
import { pushFlash } from '../stores/session'
import type { RobotSummary, TaskLocation } from '../types'
import './HomePage.css'

interface PieItem {
  name: string
  value: number
}

interface SummaryResponse {
  robot_list?: RobotSummary[]
  pie_data?: PieItem[]
  locations?: TaskLocation[]
}

const REFRESH_INTERVAL_MS = 3000

function buildRobotPopup(robot: RobotSummary) {
  const batteryText = robot.battery != null ? `${escapeHtml(robot.battery)}%` : ''
  return `<b>${escapeHtml(robot.name || '-')}</b><br>${escapeHtml(robot.device_id || '-')}<br>${escapeHtml(robot.status || '-')} ${batteryText}`
}

function renderTaskPopup(location: TaskLocation) {
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

function dotIcon(extraClass = '') {
  return L.divIcon({
    className: 'map-dot-icon',
    html: `<span class="map-dot${extraClass ? ` ${extraClass}` : ''}"></span>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  })
}

export default function HomePage() {
  const [robotList, setRobotList] = useState<RobotSummary[]>([])
  const mapElRef = useRef<HTMLDivElement>(null)
  const chartElRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const chart = echarts.init(chartElRef.current!)
    const map = L.map(mapElRef.current!, { zoomControl: false }).setView([30, 110], 5)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map)
    L.control.zoom({ position: 'topright' }).addTo(map)

    const robotMarkers: Record<string, L.Marker> = {}
    const taskMarkers: Record<string, L.Marker> = {}
    let hasAutoFocused = false
    let mapInteracted = false
    let disposed = false

    map.on('dragstart zoomstart', () => {
      mapInteracted = true
    })

    function syncRobotMarkers(robots: RobotSummary[]) {
      const activeIds = new Set<string>()
      robots.forEach((robot) => {
        if (robot.lat == null || robot.lng == null) {
          return
        }
        const id = String(robot.device_id || robot.id)
        activeIds.add(id)
        if (robotMarkers[id]) {
          robotMarkers[id].setLatLng([robot.lat, robot.lng])
          robotMarkers[id].setPopupContent(buildRobotPopup(robot))
          return
        }
        robotMarkers[id] = L.marker([robot.lat, robot.lng], { icon: dotIcon('map-dot-robot') })
          .addTo(map)
          .bindPopup(buildRobotPopup(robot))
      })
      Object.keys(robotMarkers).forEach((id) => {
        if (!activeIds.has(id)) {
          map.removeLayer(robotMarkers[id])
          delete robotMarkers[id]
        }
      })
    }

    function syncTaskMarkers(locations: TaskLocation[]) {
      const activeIds = new Set<string>()
      locations.forEach((location) => {
        if (location.lat == null || location.lng == null || location.id == null) {
          return
        }
        const id = String(location.id)
        activeIds.add(id)
        if (taskMarkers[id]) {
          taskMarkers[id].setLatLng([location.lat, location.lng])
          taskMarkers[id].setPopupContent(renderTaskPopup(location))
          return
        }
        const marker = L.marker([location.lat, location.lng], { icon: dotIcon() }).addTo(map)
        marker.bindPopup(renderTaskPopup(location), { closeButton: false, offset: L.point(0, -15) })
        marker.on('mouseover', () => marker.openPopup())
        marker.on('mouseout', () => marker.closePopup())
        taskMarkers[id] = marker
      })
      Object.keys(taskMarkers).forEach((id) => {
        if (!activeIds.has(id)) {
          map.removeLayer(taskMarkers[id])
          delete taskMarkers[id]
        }
      })
    }

    function renderPieChart(data: PieItem[]) {
      chart.setOption({
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
        const payload = await getJson<SummaryResponse>('/api/stats/summary')
        if (disposed) {
          return
        }
        const robots = payload.robot_list || []
        const locations = payload.locations || []
        setRobotList(robots)
        renderPieChart(payload.pie_data || [])
        syncRobotMarkers(robots)
        syncTaskMarkers(locations)

        if (!mapInteracted && !hasAutoFocused) {
          const focusPoints = [
            ...locations.map((item) => ({ lat: item.lat, lng: item.lng })),
            ...robots.map((item) => ({ lat: item.lat, lng: item.lng })),
          ]
          hasAutoFocused = focusMapToDenseRegion(map, focusPoints, { gridSize: 0.32, maxZoom: 15, singlePointZoom: 14 })
        }
      } catch (error) {
        if (!disposed) {
          pushFlash(errorMessage(error, '首页数据加载失败'), 'error')
        }
      }
    }

    function onResize() {
      chart.resize()
      map.invalidateSize()
    }

    const stopPolling = pollWhileVisible(loadDashboard, REFRESH_INTERVAL_MS)
    const sizeTimer = window.setTimeout(() => map.invalidateSize(), 500)
    window.addEventListener('resize', onResize)

    return () => {
      disposed = true
      stopPolling()
      window.clearTimeout(sizeTimer)
      window.removeEventListener('resize', onResize)
      chart.dispose()
      map.remove()
    }
  }, [])

  const onlineCount = robotList.filter((robot) => robot.status === 'ONLINE').length

  return (
    <div className="scope-home home-page">
      <div className="home-map-stage">
        <div id="map" ref={mapElRef} className="home-map"></div>

        <div className="home-float-panel">
          <section className="panel home-overlay-panel">
            <div className="panel-title">垃圾种类环形图</div>
            <div className="home-overlay-body">
              <div id="trashTypeChart" ref={chartElRef} className="home-donut-chart"></div>
            </div>
          </section>

          <section className="panel home-overlay-panel">
            <div className="panel-title">机器人在线状态</div>
            <div className="home-overlay-body home-table-body">
              <div className="home-status-summary">
                <span className="home-status-pill home-status-pill-online">在线 {onlineCount}</span>
                <span className="home-status-pill">总数 {robotList.length}</span>
              </div>
              <div className="home-status-table-wrap">
                <table className="home-status-table">
                  <thead>
                    <tr>
                      <th>设备ID</th>
                      <th>名称</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {robotList.map((robot) => (
                      <tr key={robot.device_id || robot.name || robot.id}>
                        <td>{robot.device_id}</td>
                        <td>{robot.name}</td>
                        <td className={robot.status === 'ONLINE' ? 'status-online-text' : 'status-offline-text'}>
                          {robot.status === 'ONLINE' ? '● 在线' : '● 离线'}
                        </td>
                      </tr>
                    ))}
                    {!robotList.length && (
                      <tr>
                        <td colSpan={3} className="home-empty-row">载入中...</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
