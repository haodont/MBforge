// PDF parse section — text chunking.

import { useTranslation } from 'react-i18next'
import SettingSection, { SettingGroup } from '@/components/ui/SettingSection'
import { NumberField, SelectField, TextField, ToggleField } from './SettingRow'
import type { SettingsState } from './types'
interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
}

export default function PdfParseSection({ settings, setSettings }: Props) {
  const { t } = useTranslation()
  return (
    <SettingSection>
      <SettingGroup title={t('settings.pdfParse')}>
        <NumberField
          label={t('settings.pdfChunkSize')}
          description={t('settings.pdfChunkSizeDesc')}
          value={settings.pdf_chunk_size}
          onChange={v => setSettings(s => ({ ...s, pdf_chunk_size: v }))}
          min={128}
          max={4096}
          step={64}
        />
        <NumberField
          label={t('settings.pdfChunkOverlap')}
          description={t('settings.pdfChunkOverlapDesc')}
          value={settings.pdf_chunk_overlap}
          onChange={v => setSettings(s => ({ ...s, pdf_chunk_overlap: v }))}
          min={0}
          max={512}
          step={16}
        />
      </SettingGroup>
      <SettingGroup title={t('settings.moldet')}>
        <ToggleField
          label={t('settings.autoMoldetOnImport')}
          description={t('settings.autoMoldetOnImportDesc')}
          value={settings.auto_moldet_on_import}
          onChange={v => setSettings(s => ({ ...s, auto_moldet_on_import: v }))}
        />
        <NumberField
          label={t('settings.moldetBatchSize')}
          description={t('settings.moldetBatchSizeDesc')}
          value={settings.detection_batch_size}
          onChange={v => setSettings(s => ({ ...s, detection_batch_size: v }))}
          min={0}
          max={100}
          step={1}
        />
      </SettingGroup>
      <SettingGroup title={t('settings.ingest')}>
        <ToggleField
          label={t('settings.autoEnqueueOnImport')}
          description={t('settings.autoEnqueueOnImportDesc')}
          value={settings.auto_enqueue_on_import}
          onChange={v => setSettings(s => ({ ...s, auto_enqueue_on_import: v }))}
        />
      </SettingGroup>
      <SettingGroup title={t('settings.moldetAdvanced')}>
        <SelectField
          label={t('settings.moldetDevice')}
          description={t('settings.moldetDeviceDesc')}
          value={settings.moldet_device}
          onChange={v => setSettings(s => ({ ...s, moldet_device: v }))}
          options={[
            { value: 'auto', label: 'Auto' },
            { value: 'cpu', label: 'CPU' },
            { value: 'cuda', label: 'CUDA' },
            { value: 'mps', label: 'MPS' },
          ]}
        />
        <TextField
          label={t('settings.moldetMolparserDir')}
          description={t('settings.moldetMolparserDirDesc')}
          value={settings.moldet_molparser_dir}
          onChange={v => setSettings(s => ({ ...s, moldet_molparser_dir: v }))}
          placeholder="/path/to/MolParser-Mobile"
          monospace
        />
        <NumberField
          label={t('settings.moldetDetectionDpi')}
          description={t('settings.moldetDetectionDpiDesc')}
          value={settings.moldet_detection_dpi}
          onChange={v => setSettings(s => ({ ...s, moldet_detection_dpi: v }))}
          min={72}
          max={600}
          step={10}
          width={120}
        />
        <NumberField
          label={t('settings.moldetMolparserBatchSize')}
          description={t('settings.moldetMolparserBatchSizeDesc')}
          value={settings.moldet_molparser_batch_size}
          onChange={v => setSettings(s => ({ ...s, moldet_molparser_batch_size: v }))}
          min={1}
          max={64}
          step={1}
          width={100}
        />
        <NumberField
          label={t('settings.moldetTextPageCharThreshold')}
          description={t('settings.moldetTextPageCharThresholdDesc')}
          value={settings.moldet_text_page_char_threshold}
          onChange={v => setSettings(s => ({ ...s, moldet_text_page_char_threshold: v }))}
          min={50}
          max={5000}
          step={50}
          width={120}
        />
        <NumberField
          label={t('settings.moldetMaxPagesPerDoc')}
          description={t('settings.moldetMaxPagesPerDocDesc')}
          value={settings.moldet_max_pages_per_doc}
          onChange={v => setSettings(s => ({ ...s, moldet_max_pages_per_doc: v }))}
          min={0}
          max={5000}
          step={1}
          width={120}
        />
      </SettingGroup>
      <SettingGroup title={t('settings.ingestAdvanced')}>
        <NumberField
          label={t('settings.ingestDefaultPriority')}
          description={t('settings.ingestDefaultPriorityDesc')}
          value={settings.ingest_default_priority}
          onChange={v => setSettings(s => ({ ...s, ingest_default_priority: v }))}
          min={0}
          max={10}
          step={1}
          width={100}
        />
      </SettingGroup>
    </SettingSection>
  )
}