import Button from '@/components/ui/Button'
import { CheckIcon, XIcon, AlertIcon } from '../icons'
import type { ValidationIssue } from '@/api/http/molecule'

interface ValidationResultProps {
  validation: {
    smiles: string
    issues: ValidationIssue[]
    canonical: string | null
    loading: boolean
  } | null
  onUseCanonical?: (canonical: string) => void
}

export default function ValidationResult({ validation, onUseCanonical }: ValidationResultProps) {
  if (!validation) return null
  const { issues, canonical, loading, smiles } = validation
  const hasErrors = issues.some(i => i.severity === 'error')
  const warnings = issues.filter(i => i.severity === 'warning')

  return (
    <div className={`mol-validation-result ${hasErrors ? 'mol-validation-result--error' : warnings.length > 0 ? 'mol-validation-result--warn' : 'mol-validation-result--success'}`}>
      <div className="mol-validation-header">
        {loading ? (
          <>
            <AlertIcon size={12} />
            <span className="mol-validation-status">结构校验中…</span>
          </>
        ) : hasErrors ? (
          <>
            <XIcon size={12} />
            <span className="mol-validation-status mol-validation-status--error">
              结构错误：{issues.find(i => i.severity === 'error')?.message}
            </span>
          </>
        ) : warnings.length > 0 ? (
          <>
            <AlertIcon size={12} />
            <span className="mol-validation-status mol-validation-status--warn">
              警告：{warnings.length} 项
            </span>
          </>
        ) : (
          <>
            <CheckIcon size={12} />
            <span className="mol-validation-status mol-validation-status--success">结构有效</span>
          </>
        )}
      </div>

      {issues.length > 0 && !loading && (
        <ul className="mol-validation-issues">
          {issues.map((issue, i) => (
            <li key={i}>
              <code className="mol-validation-code">{issue.code}</code>
              {' — '}
              {issue.message}
            </li>
          ))}
        </ul>
      )}

      {canonical && canonical !== smiles && !hasErrors && onUseCanonical && (
        <div className="mol-validation-canonical">
          <code className="mol-validation-code">canonical: {canonical}</code>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onUseCanonical(canonical)}
            title="使用规范化后的 SMILES 替换当前值"
          >
            采用
          </Button>
        </div>
      )}
    </div>
  )
}
