import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router'
import L from 'leaflet'
import { errorMessage, getJson, postJson } from '../lib/api'
import { escapeHtml } from '../lib/escape'
import { pollWhileVisible } from '../lib/polling'
import { pushFlash } from '../stores/session'

interface RobotDetail {
  id: number
  device_id?: string | null
  name?: string | null
  status?: string | null
  battery?: number | null
  lat?: number | null
  lng?: number | null
  target?: { lat?: number | null; lng?: number | null } | null
  last_heartbeat?: string | null
}

const CONTROL_COMMANDS = [
  'FORWARD', 'LEFT', 'STOP', 'RIGHT', 'BACK', 'PICK_TRASH', 'SLOW_FORWARD', 'FAST_FORWARD',
  'SPIN_LEFT', 'SPIN_RIGHT', 'PAUSE', 'RESUME', 'CANCEL_NAVIGATION', 'HOLD_POSITION', 'RETURN_HOME', 'DOCK',
]

const POLL_INTERVAL_MS = 2000

function buildRobotPopup(robot: RobotDetail | null) {
  return `<b>${escapeHtml(robot?.name || '-')}</b><br>${escapeHtml(robot?.device_id || '-')}`
}

function dotIcon(extraClass: string) {
  return L.divIcon({ className: 'map-dot-icon', html: `<span class="map-dot ${extraClass}"></span>`, iconSize: [14, 14], iconAnchor: [7, 7] })
}

function formatLatLng(lat?: number | null, lng?: number | null) {
  return lat != null && lng != null ? `${lat.toFixed(5)}, ${lng.toFixed(5)}` : '--'
}

export default function RobotControlPage() {
  const { id: robotId = '' } = useParams()
  const [robot, setRobot] = useState<RobotDetail | null>(null)
  const [streamUrl, setStreamUrl] = useState('')
  const [customCmd, setCustomCmd] = useState('')
  const [navLat, setNavLat] = useState('')
  const [navLng, setNavLng] = useState('')
  const [cameraSrc, setCameraSrc] = useState('')

  const mapElRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const robotMarkerRef = useRef<L.Marker | null>(null)
  const targetMarkerRef = useRef<L.Marker | null>(null)

  useEffect(() => {
    const map = L.map(mapElRef.current!).setView([30, 110], 6)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map)
    mapRef.current = map

    const onResize = () => map.invalidateSize()
    const sizeTimer = window.setTimeout(onResize, 500)
    window.addEventListener('resize', onResize)

    return () => {
      window.clearTimeout(sizeTimer)
      window.removeEventListener('resize', onResize)
      map.remove()
      mapRef.current = null
      robotMarkerRef.current = null
      targetMarkerRef.current = null
    }
  }, [])

  const applyRobot = useCallback((currentRobot: RobotDetail | null) => {
    setRobot(currentRobot)
    const map = mapRef.current
    if (!map) {
      return
    }
    if (currentRobot?.lat != null && currentRobot?.lng != null) {
      if (robotMarkerRef.current) {
        robotMarkerRef.current.setLatLng([currentRobot.lat, currentRobot.lng])
        robotMarkerRef.current.setPopupContent(buildRobotPopup(currentRobot))
      } else {
        robotMarkerRef.current = L.marker([currentRobot.lat, currentRobot.lng], { icon: dotIcon('map-dot-robot') })
          .addTo(map)
          .bindPopup(buildRobotPopup(currentRobot))
        map.setView([currentRobot.lat, currentRobot.lng], 16)
      }
    }
    const target = currentRobot?.target
    if (target?.lat != null && target?.lng != null) {
      if (targetMarkerRef.current) {
        targetMarkerRef.current.setLatLng([target.lat, target.lng])
      } else {
        targetMarkerRef.current = L.marker([target.lat, target.lng], { icon: dotIcon('map-dot-robot-target') })
          .addTo(map)
          .bindPopup('目标位置')
      }
    }
  }, [])

  const loadRobot = useCallback(async () => {
    try {
      const [detailPayload, listPayload] = await Promise.all([
        getJson<{ robot: RobotDetail }>(`/api/web/robots/${robotId}`),
        getJson<{ robots?: RobotDetail[] }>('/api/robot/live/list').catch(() => getJson<{ robots?: RobotDetail[] }>('/api/robot/list')),
      ])
      const realtimeRobot = (listPayload.robots || []).find((item) => Number(item.id) === Number(robotId))
      applyRobot(realtimeRobot || detailPayload.robot)
    } catch (error) {
      pushFlash(errorMessage(error, '机器人详情加载失败'), 'error')
    }
  }, [robotId, applyRobot])

  useEffect(() => {
    return pollWhileVisible(loadRobot, POLL_INTERVAL_MS)
  }, [loadRobot])

  async function sendCommand(command: string, sourceText = '发送控制命令') {
    try {
      const payload = await postJson('/api/robot/control', { id: Number(robotId), command })
      pushFlash(`${sourceText}: ${payload.command || command}`, 'success')
    } catch (error) {
      pushFlash(errorMessage(error, '命令发送失败'), 'error')
    }
  }

  async function sendNavigation() {
    const lat = navLat.trim()
    const lng = navLng.trim()
    if (!lat || !lng) {
      pushFlash('请填写目标经纬度', 'warning')
      return
    }
    try {
      const payload = await postJson('/api/robot/navigate', { id: Number(robotId), lat: Number(lat), lng: Number(lng) })
      pushFlash(payload.msg || '导航目标已设置', 'success')
      await loadRobot()
    } catch (error) {
      pushFlash(errorMessage(error, '导航设置失败'), 'error')
    }
  }

  function setStream() {
    const url = streamUrl.trim()
    if (!url) {
      pushFlash('请输入流地址', 'warning')
      return
    }
    setCameraSrc(url)
    pushFlash('摄像头流已设置', 'success')
  }

  return (
    <div className="layout-content">
      <div className="layout-left robot-control-left">
        <div className="layout-inner-left">
          <div className="panel">
            <div className="panel-title">机载摄像头</div>
            <div className="chart-wrap robot-control-stack">
              <img src={cameraSrc || undefined} alt="camera" className="robot-camera" />
              <div className="form-row">
                <input
                  value={streamUrl}
                  onChange={(event) => setStreamUrl(event.target.value)}
                  placeholder="摄像头流地址（例如 http://192.168.1.100:8080/stream）"
                  className="input-control"
                />
                <button type="button" onClick={setStream}>设置</button>
              </div>
              <div className="robot-cmd-grid">
                {CONTROL_COMMANDS.map((command) => (
                  <button key={command} type="button" className="ctl-btn" onClick={() => sendCommand(command)}>{command}</button>
                ))}
              </div>
              <div className="form-row">
                <input
                  value={customCmd}
                  onChange={(event) => setCustomCmd(event.target.value)}
                  className="input-control"
                  placeholder="自定义指令（如 RESET）"
                />
                <button type="button" onClick={() => sendCommand(customCmd.trim(), '发送自定义指令')}>发送指令</button>
              </div>

              <div className="robot-status-card">
                <div className="robot-status-header">
                  <div className="robot-name">{robot?.name || '-'}</div>
                  <div className="robot-device">ID: {robot?.device_id || '-'}</div>
                  <span id="robotStatusBadge" className={`status-badge ${robot?.status === 'ONLINE' ? 'status-online' : 'status-offline'}`}>
                    {robot?.status || 'OFFLINE'}
                  </span>
                </div>
                <div className="robot-status-row">
                  <span className="label">电量</span>
                  <div className="battery-bar">
                    <div id="robotBatteryBar" className="battery-bar-inner" style={{ width: `${robot?.battery || 0}%` }}></div>
                  </div>
                  <span id="robotBatteryText" className="value">{robot?.battery != null ? `${robot.battery}%` : '-'}</span>
                </div>
                <div className="robot-status-row">
                  <span className="label">位置</span>
                  <span id="robotPosition" className="value">{formatLatLng(robot?.lat, robot?.lng)}</span>
                </div>
                <div className="robot-status-row">
                  <span className="label">目标</span>
                  <span id="robotTarget" className="value">{formatLatLng(robot?.target?.lat, robot?.target?.lng)}</span>
                </div>
                <div className="robot-status-row">
                  <span className="label">上线时间</span>
                  <span id="robotLastHeartbeat" className="value">{robot?.last_heartbeat || '--'}</span>
                </div>
                <div className="robot-status-row">
                  <span className="label">导航</span>
                  <div className="robot-nav-inline">
                    <input value={navLat} onChange={(event) => setNavLat(event.target.value)} className="input-control input-sm" placeholder="目标纬度" />
                    <input value={navLng} onChange={(event) => setNavLng(event.target.value)} className="input-control input-sm" placeholder="目标经度" />
                    <button id="btnSetNav" type="button" className="btn-sm" onClick={sendNavigation}>设置</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="layout-center robot-control-right">
        <div className="panel">
          <div className="panel-title">实时地图与导航</div>
          <div className="chart-wrap map-wrap">
            <div className="map-box">
              <div id="robotControlMap" ref={mapElRef} className="robot-control-map"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
