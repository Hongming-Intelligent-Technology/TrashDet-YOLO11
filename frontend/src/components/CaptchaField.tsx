import type { CaptchaState } from '../hooks/useCaptchaChallenge'

interface CaptchaFieldProps {
  captcha: CaptchaState
  loading: boolean
  value: string
  onChange: (value: string) => void
  onRefresh: () => void
}

export default function CaptchaField({ captcha, loading, value, onChange, onRefresh }: CaptchaFieldProps) {
  if (!captcha.enabled) {
    return null
  }
  return (
    <div className="field-block">
      <label htmlFor="captcha_text">图形验证码</label>
      <div className="captcha-row">
        <input
          id="captcha_text"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          type="text"
          maxLength={8}
          required
          placeholder="请输入验证码"
        />
        {captcha.image_data && <img src={captcha.image_data} alt="captcha" className="captcha-image" />}
        <button type="button" className="captcha-refresh" disabled={loading} onClick={onRefresh}>
          {loading ? '加载中...' : '刷新'}
        </button>
      </div>
    </div>
  )
}
