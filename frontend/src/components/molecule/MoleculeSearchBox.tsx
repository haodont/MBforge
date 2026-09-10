import { useTranslation } from 'react-i18next'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import { SearchIcon, XIcon } from '../icons'

interface MoleculeSearchBoxProps {
  query: string
  onQueryChange: (q: string) => void
  disabled?: boolean
}

export default function MoleculeSearchBox({
  query,
  onQueryChange,
  disabled = false,
}: MoleculeSearchBoxProps) {
  const { t } = useTranslation()

  return (
    <div className="molecule-filters__search-row">
      <SearchIcon size={18} />
      <Input
        type="text"
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        placeholder={t('mol.search')}
        disabled={disabled}
        className="molecule-filters__search-input"
        ariaLabel={t('mol.search')}
      />
      {query && (
        <Button
          variant="ghost"
          size="sm"
          icon={<XIcon size={15} />}
          onClick={() => onQueryChange('')}
          disabled={disabled}
          title={t('mol.clearSearch')}
        />
      )}
      {disabled && (
        <span className="molecule-filters__search-status" role="status">
          {t('mol.searching')}
        </span>
      )}
    </div>
  )
}
