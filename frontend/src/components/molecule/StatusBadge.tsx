import { useTranslation } from 'react-i18next'
import Badge from '@/components/ui/Badge'
import type { CorrectionItem } from './CorrectionPanel'

interface StatusBadgeProps {
  status: CorrectionItem['status']
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const { t } = useTranslation()
  switch (status) {
    case 'confirmed':
      return <Badge variant="success" dot>{t('mol.status.confirmed')}</Badge>
    case 'corrected':
      return <Badge variant="info" dot>{t('mol.status.corrected')}</Badge>
    case 'rejected':
      return <Badge variant="danger" dot>{t('mol.status.rejected')}</Badge>
    default:
      return <Badge variant="warning" dot>{t('mol.status.pending')}</Badge>
  }
}
