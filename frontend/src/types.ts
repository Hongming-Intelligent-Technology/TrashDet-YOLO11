/** Shapes of the backend JSON payloads used by several pages. */

export interface Pagination {
  page: number
  pages?: number
  total?: number
  has_prev: boolean
  has_next: boolean
  prev_num?: number | null
  next_num?: number | null
}

export interface TaskRow {
  id: number
  source_type?: string | null
  source_path?: string | null
  result_path?: string | null
  device_id?: string | null
  location?: string | null
  display_location?: string | null
  status?: string | null
  error_msg?: string | null
  user_id?: number | null
  latitude?: number | null
  longitude?: number | null
  created_at?: string | null
}

export interface DetectItemRow {
  id: number
  task_id?: number
  label?: string | null
  confidence?: number | null
  handle_state?: string | null
  bbox?: Array<number | null>
  frame_index?: number | null
  snapshot_path?: string | null
  captured_at?: string | null
}

export interface RobotSummary {
  id?: number
  device_id?: string | null
  name?: string | null
  status?: string | null
  battery?: number | null
  lat?: number | null
  lng?: number | null
}

export interface TaskLocation {
  id: number
  lat: number | null
  lng: number | null
  trash_types?: string | null
}
