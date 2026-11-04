<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import L from 'leaflet'
import { getJson, postJson } from '../lib/api'
import { escapeHtml } from '../lib/escape'
import { pushFlash } from '../stores/session'

const route = useRoute()
const robot = ref(null)
const streamUrl = ref('')
const customCmd = ref('')
const navLat = ref('')
const navLng = ref('')
const cameraSrc = ref('')
const robotId = computed(() => route.params.id)
let map = null
let robotMarker = null
let targetMarker = null
let pollTimer = null

async function runRobotMutation(requestFactory, onSuccess, fallbackError) {
  try {
    const payload = await requestFactory()
    await onSuccess(payload)
  } catch (error) {
    pushFlash(error.message || fallbackError, 'error')
  }
}

function buildRobotPopup(currentRobot) {
  return `<b>${escapeHtml(currentRobot?.name || '-')}</b><br>${escapeHtml(currentRobot?.device_id || '-')}`
}

function applyRobot(currentRobot) {
  robot.value = currentRobot
  if (currentRobot?.lat != null && currentRobot?.lng != null && map) {
    if (robotMarker) {
      robotMarker.setLatLng([currentRobot.lat, currentRobot.lng])
      robotMarker.setPopupContent(buildRobotPopup(currentRobot))
    } else {
      robotMarker = L.marker([currentRobot.lat, currentRobot.lng], {
        icon: L.divIcon({ className: 'map-dot-icon', html: '<span class="map-dot map-dot-robot"></span>', iconSize: [14, 14], iconAnchor: [7, 7] }),
      }).addTo(map).bindPopup(buildRobotPopup(currentRobot))
      map.setView([currentRobot.lat, currentRobot.lng], 16)
    }
  }
  if (currentRobot?.target?.lat != null && currentRobot?.target?.lng != null && map) {
    if (targetMarker) {
      targetMarker.setLatLng([currentRobot.target.lat, currentRobot.target.lng])
    } else {
      targetMarker = L.marker([currentRobot.target.lat, currentRobot.target.lng], {
        icon: L.divIcon({ className: 'map-dot-icon', html: '<span class="map-dot map-dot-robot-target"></span>', iconSize: [14, 14], iconAnchor: [7, 7] }),
      }).addTo(map).bindPopup('目标位置')
    }
  }
}

async function loadRobot() {
  try {
    const [detailPayload, listPayload] = await Promise.all([
      getJson(`/api/web/robots/${robotId.value}`),
      (async () => {
        try {
          return await getJson('/api/robot/live/list')
        } catch (liveError) {
          return getJson('/api/robot/list')
        }
      })(),
    ])
    const baseRobot = detailPayload.robot
    const realtimeRobot = (listPayload.robots || []).find((item) => Number(item.id) === Number(robotId.value))
    applyRobot(realtimeRobot || baseRobot)
  } catch (error) {
    pushFlash(error.message || '机器人详情加载失败', 'error')
  }
}

async function sendCommand(command, sourceText = '发送控制命令') {
  await runRobotMutation(
    () => postJson('/api/robot/control', { id: Number(robotId.value), command }),
    async (payload) => {
      pushFlash(`${sourceText}: ${payload.command || command}`, 'success')
    },
    '命令发送失败',
  )
}

async function sendNavigation() {
  if (!navLat.value || !navLng.value) {
    pushFlash('请填写目标经纬度', 'warning')
    return
  }
  await runRobotMutation(
    () => postJson('/api/robot/navigate', {
      id: Number(robotId.value),
      lat: Number(navLat.value),
      lng: Number(navLng.value),
    }),
    async (payload) => {
      pushFlash(payload.msg || '导航目标已设置', 'success')
      await loadRobot()
    },
    '导航设置失败',
  )
}

function setStream() {
  if (!streamUrl.value.trim()) {
    pushFlash('请输入流地址', 'warning')
    return
  }
  cameraSrc.value = streamUrl.value.trim()
  pushFlash('摄像头流已设置', 'success')
}

function onResize() {
  map?.invalidateSize()
}

watch(() => route.params.id, loadRobot)

onMounted(() => {
  navLat.value = ''
  navLng.value = ''
  map = L.map('robotControlMap').setView([30, 110], 6)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map)
  loadRobot()
  pollTimer = window.setInterval(loadRobot, 2000)
  window.setTimeout(() => map?.invalidateSize(), 500)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  window.removeEventListener('resize', onResize)
  map?.remove()
})
</script>

<template>
  <div class="layout-content">
    <div class="layout-left robot-control-left">
      <div class="layout-inner-left">
        <div class="panel">
          <div class="panel-title">机载摄像头</div>
          <div class="chart-wrap robot-control-stack">
            <img :src="cameraSrc" alt="camera" class="robot-camera">
            <div class="form-row">
              <input v-model.trim="streamUrl" placeholder="摄像头流地址（例如 http://192.168.1.100:8080/stream）"
                class="input-control">
              <button type="button" @click="setStream">设置</button>
            </div>
            <div class="robot-cmd-grid">
              <button
                v-for="command in ['FORWARD', 'LEFT', 'STOP', 'RIGHT', 'BACK', 'PICK_TRASH', 'SLOW_FORWARD', 'FAST_FORWARD', 'SPIN_LEFT', 'SPIN_RIGHT', 'PAUSE', 'RESUME', 'CANCEL_NAVIGATION', 'HOLD_POSITION', 'RETURN_HOME', 'DOCK']"
                :key="command" type="button" class="ctl-btn" @click="sendCommand(command)">{{ command }}</button>
            </div>
            <div class="form-row">
              <input v-model.trim="customCmd" class="input-control" placeholder="自定义指令（如 RESET）">
              <button type="button" @click="sendCommand(customCmd, '发送自定义指令')">发送指令</button>
            </div>

            <div class="robot-status-card">
              <div class="robot-status-header">
                <div class="robot-name">{{ robot?.name || '-' }}</div>
                <div class="robot-device">ID: {{ robot?.device_id || '-' }}</div>
                <span id="robotStatusBadge" class="status-badge"
                  :class="robot?.status === 'ONLINE' ? 'status-online' : 'status-offline'">{{ robot?.status || 'OFFLINE'
                  }}</span>
              </div>
              <div class="robot-status-row"><span class="label">电量</span>
                <div class="battery-bar">
                  <div id="robotBatteryBar" class="battery-bar-inner" :style="{ width: `${robot?.battery || 0}%` }">
                  </div>
                </div><span id="robotBatteryText" class="value">{{ robot?.battery != null ? `${robot.battery}%` : '-'
                }}</span>
              </div>
              <div class="robot-status-row"><span class="label">位置</span><span id="robotPosition" class="value">{{
                robot?.lat != null && robot?.lng != null ? `${robot.lat.toFixed(5)}, ${robot.lng.toFixed(5)}` : '--'
              }}</span></div>
              <div class="robot-status-row"><span class="label">目标</span><span id="robotTarget" class="value">{{
                robot?.target?.lat != null && robot?.target?.lng != null ? `${robot.target.lat.toFixed(5)},
                  ${robot.target.lng.toFixed(5)}` : '--' }}</span></div>
              <div class="robot-status-row"><span class="label">上线时间</span><span id="robotLastHeartbeat"
                  class="value">{{ robot?.last_heartbeat || '--' }}</span></div>
              <div class="robot-status-row">
                <span class="label">导航</span>
                <div class="robot-nav-inline">
                  <input v-model.trim="navLat" class="input-control input-sm" placeholder="目标纬度">
                  <input v-model.trim="navLng" class="input-control input-sm" placeholder="目标经度">
                  <button id="btnSetNav" type="button" class="btn-sm" @click="sendNavigation">设置</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="layout-center robot-control-right">
      <div class="panel">
        <div class="panel-title">实时地图与导航</div>
        <div class="chart-wrap map-wrap">
          <div class="map-box">
            <div id="robotControlMap" class="robot-control-map"></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
