/** Types and helpers shared by the user admin page and its sections. */

export interface UserRow {
  id: number
  username?: string
  organization?: string | null
  role?: string
  is_current_user?: boolean
}

// A type alias (not an interface) so it fits fieldUpdater's Record<string, unknown> constraint.
export type ProfileForm = {
  username: string
  organization: string
  password: string
  confirm_password: string
}

export const EMPTY_PROFILE_FORM: ProfileForm = { username: '', organization: '', password: '', confirm_password: '' }

/** Editable profile fields of a user row, with empty password fields. */
export function profileFormFrom(row: UserRow | null | undefined): ProfileForm {
  return row
    ? { username: row.username || '', organization: row.organization || '', password: '', confirm_password: '' }
    : EMPTY_PROFILE_FORM
}

/** Profile fields as sent to the backend: names trimmed, passwords as typed. */
export function profilePayload(form: ProfileForm) {
  return {
    username: form.username.trim(),
    organization: form.organization.trim(),
    password: form.password,
    confirm_password: form.confirm_password,
  }
}

export function roleText(role?: string) {
  return role === 'admin' ? '管理员' : '普通用户'
}
