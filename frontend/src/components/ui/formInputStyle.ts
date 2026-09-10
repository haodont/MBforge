import type { CSSProperties } from 'react'

/**
 * Compact form input style. Slightly denser than the default `.input`
 * class (used by `<Input>`): 6×10 padding instead of 8×12, font 13
 * instead of the base size. Apply via `style={compactInputStyle}` when
 * the default `<Input>` looks too loose for dense forms.
 */
export const compactInputStyle: CSSProperties = {
  padding: '6px 10px',
  fontSize: 13,
  borderRadius: 6,
  border: '1px solid var(--border)',
  background: 'var(--bg-base)',
  color: 'var(--text-primary)',
  fontFamily: 'inherit',
  outline: 'none',
}