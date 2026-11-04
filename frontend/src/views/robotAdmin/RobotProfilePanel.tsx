import { Link } from 'react-router'
import { ROBOT_STATUSES, statusClass, type Robot } from './shared'

interface Props {
  robot: Robot
  address: { address: string; loading: boolean; error: string }
  editName: string
  editStatus: string
  onEditNameChange: (value: string) => void
  onEditStatusChange: (value: string) => void
  onSave: () => void
  onDelete: () => void
}

/** "机器人管理" tab of the editor drawer: status, location and profile editing. */
export default function RobotProfilePanel({
  robot,
  address,
  editName,
  editStatus,
  onEditNameChange,
  onEditStatusChange,
  onSave,
  onDelete,
}: Props) {
  return (
    <div className="drawer-body">
      <div className="robot-quick-grid">
        <div className="quick-card">
          <div className="quick-label">在线状态</div>
          <div className={`quick-value ${statusClass(robot.status)}`}>{robot.status || 'UNKNOWN'}</div>
        </div>
        <div className="quick-card quick-card-wide">
          <div className="quick-label">当前位置</div>
          <div className="quick-value quick-address-value">
            {address.loading ? '地址解析中...' : address.address || '暂无定位信息'}
          </div>
          {address.error && <div className="quick-subvalue">{address.error}</div>}
        </div>
      </div>

      <input value={editName} onChange={(event) => onEditNameChange(event.target.value)} className="input-control" placeholder="机器人名称" />
      <select value={editStatus} onChange={(event) => onEditStatusChange(event.target.value)} className="input-control">
        {ROBOT_STATUSES.map((status) => (
          <option key={status} value={status}>{status}</option>
        ))}
      </select>
      <div className="drawer-actions robot-actions">
        <button type="button" className="square-btn robot-action-btn" onClick={onSave}>保存机器人</button>
        <button type="button" className="square-btn btn-delete robot-action-btn" onClick={onDelete}>删除机器人</button>
        <Link className="square-btn robot-action-btn" to={`/robot/${robot.id}`}>手动控制</Link>
      </div>
    </div>
  )
}
