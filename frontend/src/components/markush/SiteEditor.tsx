/**
 * Markush site / option / mount editor.
 *
 * Mounted from MarkushReviewPanel when the review candidate has been
 * confirmed as a scaffold (so a ``scaffold_id`` is available). The editor
 * surfaces Phase-4 invariants:
 *
 * - Every site carries an explicit ``atom_map_num``; implicit mapping by
 *   ``*`` order is disallowed and rejected by the API.
 * - A mount between a site and a fragment must have matching attachment
 *   counts. The backend enforces this; the UI shows the
 *   current state and the human-supplied confidence / origin.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useMarkushCreateMount,
  useMarkushCreateOption,
  useMarkushCreateSite,
  useMarkushDecideMount,
  useMarkushMounts,
  useMarkushOptions,
  useMarkushSites,
  useMarkushUpdateSite,
} from '@/api/query/useMarkush'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Tag from '../ui/Tag'

interface SiteEditorProps {
  libraryRoot: string
  scaffoldId: string
  /** Suggested number of attachment points parsed from the scaffold SMILES. */
  attachmentHint?: number
}

export default function SiteEditor({
  libraryRoot,
  scaffoldId,
  attachmentHint,
}: SiteEditorProps) {
  const { t } = useTranslation()
  const sites = useMarkushSites(libraryRoot, scaffoldId)
  const mounts = useMarkushMounts(libraryRoot, { scaffold_id: scaffoldId })

  const createSite = useMarkushCreateSite(libraryRoot)
  const updateSite = useMarkushUpdateSite(libraryRoot)
  const createOption = useMarkushCreateOption(libraryRoot)
  const createMount = useMarkushCreateMount(libraryRoot)
  const decideMount = useMarkushDecideMount(libraryRoot)

  const [label, setLabel] = useState('')
  const [atomMap, setAtomMap] = useState('')
  const [attachmentCount, setAttachmentCount] = useState('1')

  return (
    <section
      data-testid="markush-site-editor"
      style={{
        padding: '12px 14px',
        borderTop: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 600 }}>
        {t('markush.site.title', '骨架 attachment site 编辑器')}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'flex-end' }}>
        <Field
          label={t('markush.site.label', 'site_label (e.g. R1)')}
          value={label}
          onChange={setLabel}
        />
        <Field
          label={t('markush.site.atomMap', 'atom_map_num')}
          value={atomMap}
          onChange={setAtomMap}
        />
        <Field
          label={t('markush.site.attachmentCount', 'attachment_count')}
          value={attachmentCount}
          onChange={setAttachmentCount}
        />
        <Button
          size="sm"
          variant="primary"
          disabled={
            !label ||
            !atomMap ||
            createSite.isPending ||
            (attachmentHint != null && Number(atomMap) > attachmentHint)
          }
          onClick={() => {
            createSite.mutate(
              {
                scaffold_id: scaffoldId,
                site_label: label,
                atom_map_num: Number(atomMap),
                attachment_count: Number(attachmentCount || '1'),
              },
              {
                onSuccess: () => {
                  setLabel('')
                  setAtomMap('')
                  setAttachmentCount('1')
                },
              },
            )
          }}
        >
          {t('markush.site.add', '新增 site')}
        </Button>
      </div>

      {attachmentHint != null ? (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {t(
            'markush.site.attachmentHint',
            '骨架检测到 {{n}} 个 * attachment point。',
            { n: attachmentHint },
          )}
        </div>
      ) : null}

      {sites.isLoading ? (
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('common.loading', '加载中…')}</div>
      ) : sites.data && sites.data.length > 0 ? (
        <ol style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {sites.data.map((site) => (
            <li
              key={site.site_id}
              style={{
                padding: 10,
                background: 'var(--bg-base)',
                border: '1px solid var(--border)',
                borderRadius: 8,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ fontWeight: 600 }}>
                  {site.site_label}
                  <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                    [*:{site.atom_map_num ?? '?'}]
                  </span>
                  <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                    attach={site.attachment_count}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={updateSite.isPending || !site.atom_map_num}
                    onClick={() =>
                      updateSite.mutate({
                        site_id: site.site_id,
                        attachment_count: site.attachment_count + 1,
                      })
                    }
                  >
                    {t('markush.site.incrementAttach', 'attach_count+1')}
                  </Button>
                </div>
              </div>
              <SiteOptions
                libraryRoot={libraryRoot}
                siteId={site.site_id}
                createOption={createOption}
              />
              <SiteMounts
                libraryRoot={libraryRoot}
                siteId={site.site_id}
                scaffoldId={scaffoldId}
                createMount={createMount}
                decideMount={decideMount}
              />
            </li>
          ))}
        </ol>
      ) : (
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {t('markush.site.empty', '尚无 site；用上方表单新增。')}
        </div>
      )}

      {mounts.data && mounts.data.length > 0 ? (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {t('markush.site.mountCount', '共 {{n}} 个 mount。', { n: mounts.data.length })}
        </div>
      ) : null}
    </section>
  )
}

function SiteOptions({
  libraryRoot,
  siteId,
  createOption,
}: {
  libraryRoot: string
  siteId: string
  createOption: ReturnType<typeof useMarkushCreateOption>
}) {
  const { t } = useTranslation()
  const options = useMarkushOptions(libraryRoot, siteId)
  const [smiles, setSmiles] = useState('')
  const [definition, setDefinition] = useState('')

  return (
    <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ fontSize: 11, fontWeight: 600 }}>
        {t('markush.option.title', 'R-group 选项')}
      </div>
      {options.data && options.data.length > 0 ? (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: 11 }}>
          {options.data.map((opt) => (
            <li key={opt.option_id} style={{ padding: '2px 0' }}>
              {opt.normalized_smiles || opt.definition_text || opt.fragment_id || '—'}
              <span style={{ marginLeft: 6, color: 'var(--text-muted)' }}>{opt.status}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <div style={{ display: 'flex', gap: 6 }}>
        <Input
          ariaLabel={t('markush.option.smiles', 'SMILES')}
          value={smiles}
          onChange={(e) => setSmiles(e.target.value)}
          placeholder={t('markush.option.smiles', 'SMILES')}
          style={{ flex: 1, minWidth: 0, fontSize: 11 }}
        />
        <Input
          ariaLabel={t('markush.option.definition', 'definition')}
          value={definition}
          onChange={(e) => setDefinition(e.target.value)}
          placeholder={t('markush.option.definition', '定义 (e.g. C1-6 alkyl)')}
          style={{ flex: 2, minWidth: 0, fontSize: 11 }}
        />
        <Button
          size="sm"
          variant="ghost"
          disabled={!smiles && !definition}
          onClick={() => {
            createOption.mutate(
              {
                site_id: siteId,
                normalized_smiles: smiles || null,
                definition_text: definition,
              },
              {
                onSuccess: () => {
                  setSmiles('')
                  setDefinition('')
                },
              },
            )
          }}
        >
          {t('markush.option.add', '新增选项')}
        </Button>
      </div>
    </div>
  )
}

function SiteMounts({
  libraryRoot,
  siteId,
  scaffoldId: _scaffoldId,
  createMount,
  decideMount,
}: {
  libraryRoot: string
  siteId: string
  scaffoldId: string
  createMount: ReturnType<typeof useMarkushCreateMount>
  decideMount: ReturnType<typeof useMarkushDecideMount>
}) {
  const { t } = useTranslation()
  const mounts = useMarkushMounts(libraryRoot, { site_id: siteId })
  const [fragmentId, setFragmentId] = useState('')

  return (
    <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ fontSize: 11, fontWeight: 600 }}>
        {t('markush.mount.title', '挂载关系')}
      </div>
      {mounts.data && mounts.data.length > 0 ? (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: 11 }}>
          {mounts.data.map((m) => (
            <li
              key={m.mount_id}
              style={{
                display: 'flex',
                gap: 8,
                alignItems: 'center',
                padding: '2px 0',
              }}
            >
              <code style={{ fontFamily: "'Consolas', monospace" }}>{m.fragment_id}</code>
              <span style={{ color: 'var(--text-muted)' }}>{m.origin}</span>
              <Tag
                tone={m.status === 'confirmed' ? 'success' : m.status === 'rejected' ? 'danger' : 'neutral'}
              >
                {m.status}
              </Tag>
              {m.status === 'suggested' ? (
                <div style={{ display: 'flex', gap: 4 }}>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      decideMount.mutate({ mount_id: m.mount_id, action: 'confirm' })
                    }
                  >
                    {t('markush.mount.confirm', '确认')}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      decideMount.mutate({ mount_id: m.mount_id, action: 'reject' })
                    }
                  >
                    {t('markush.mount.reject', '驳回')}
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      <div style={{ display: 'flex', gap: 6 }}>
        <Input
          ariaLabel={t('markush.mount.fragmentId', 'fragment_id')}
          value={fragmentId}
          onChange={(e) => setFragmentId(e.target.value)}
          placeholder={t('markush.mount.fragmentId', 'fragment_id')}
          style={{ flex: 1, minWidth: 0, fontSize: 11 }}
        />
        <Button
          size="sm"
          variant="ghost"
          disabled={!fragmentId}
          onClick={() => {
            createMount.mutate(
              {
                site_id: siteId,
                fragment_id: fragmentId,
                origin: 'manual',
              },
              {
                onSuccess: () => setFragmentId(''),
              },
            )
          }}
        >
          {t('markush.mount.add', '新增挂载')}
        </Button>
      </div>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (next: string) => void
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{label}</span>
      <Input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          flex: 1,
          minWidth: 0,
          fontSize: 11,
          fontFamily: "'Consolas', monospace",
        }}
      />
    </label>
  )
}
