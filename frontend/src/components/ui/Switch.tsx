export interface SwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  size?: 'sm' | 'md'
  style?: React.CSSProperties
  className?: string
  ariaLabel?: string
}

/**
 * Switch 开关组件。
 *
 * settings/SettingRow.tsx 中的 ToggleField 组合此控件与设置标题。
 * 视觉样式由 styles/ui.css 的 .ui-switch 类族承载。
 */
export default function Switch({
  checked,
  onChange,
  disabled = false,
  size = 'md',
  style,
  className,
  ariaLabel,
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
        aria-label={ariaLabel}
      />
      <span className="ui-switch__track">
        <span className="ui-switch__thumb" />
      </span>
    </label>
  )
}
