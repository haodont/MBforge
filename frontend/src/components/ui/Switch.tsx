export interface SwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  size?: 'sm' | 'md'
  style?: React.CSSProperties
  className?: string
}

/**
 * Switch 开关组件。
 *
 * 替代 settings/SettingRow.tsx 中的 ToggleField，提升复用性。
 * 视觉样式由 styles/ui.css 的 .ui-switch 类族承载。
 */
export default function Switch({
  checked,
  onChange,
  disabled = false,
  size = 'md',
  style,
  className,
}: SwitchProps) {
  const cls = ['ui-switch', `ui-switch--${size}`, disabled && 'ui-switch--disabled', className]
    .filter(Boolean)
    .join(' ')

  return (
    <label className={cls} style={style}>
      <input
        type="checkbox"
        className="ui-switch__input"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
      />
      <span className="ui-switch__track">
        <span className="ui-switch__thumb" />
      </span>
    </label>
  )
}
