import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PageContainer, Button, Input, TextArea, InlineAlert, ProgressBar, ScrollColumn, Select } from '@/components/ui'
import { TrashIcon, TargetIcon } from '@/components/icons'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'
import {
  dockingPoseUrl,
  dockingReceptorFileUrl,
  type DockingBox,
  type DockingLigandInput,
} from '@/api/http/docking'
import {
  useCancelDockingJob,
  useCreateDockingJob,
  useDeleteReceptor,
  useDockingEngine,
  useDockingJob,
  useDockingJobs,
  useReceptors,
  useUploadReceptor,
} from '@/api/query/hooks'
import StructureViewer3D from './StructureViewer3D'
import DockingAgentPanel from './DockingAgentPanel'
import './docking.css'

/** Parse "label = SMILES" lines (label optional) into ligand inputs. */
function parseLigands(text: string): DockingLigandInput[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const separator = line.indexOf('=')
      const label = separator >= 0 ? line.slice(0, separator).trim() : ''
      const smiles = (separator >= 0 ? line.slice(separator + 1) : line).trim()
      return { smiles, label: label || `ligand-${index + 1}` }
    })
    .filter((ligand) => ligand.smiles.length > 0)
}

const num = (value: string, fallback: number): number => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export default function DockingPage() {
  const { t } = useTranslation()
  const engine = useDockingEngine()
  const receptors = useReceptors()
  const jobs = useDockingJobs()

  const [selectedReceptorId, setSelectedReceptorId] = useState<string>('')
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)
  const [selectedPoseId, setSelectedPoseId] = useState<string | null>(null)
  const [ligandsText, setLigandsText] = useState('')
  const [center, setCenter] = useState(['0', '0', '0'])
  const [size, setSize] = useState(['20', '20', '20'])
  const [exhaustiveness, setExhaustiveness] = useState('8')
  const [numModes, setNumModes] = useState('9')
  const [seed, setSeed] = useState('0')
  const [searchMode, setSearchMode] = useState('balance')
  const [scoring, setScoring] = useState('vina')
  const [uploadName, setUploadName] = useState('')
  const [uploadPercent, setUploadPercent] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const uploadMutation = useUploadReceptor()
  const deleteMutation = useDeleteReceptor()
  const createJob = useCreateDockingJob()
  const cancelJob = useCancelDockingJob()
  const jobDetail = useDockingJob(selectedJobId)

  const receptorList = receptors.data?.receptors ?? []
  const jobList = jobs.data?.jobs ?? []
  const activeReceptor = receptorList.find((r) => r.receptor_id === selectedReceptorId)
  const job = jobDetail.data?.job
  const poses = job?.poses ?? []
  const activePose = poses.find((p) => p.pose_id === selectedPoseId)

  const box: DockingBox = useMemo(
    () => ({
      center: [num(center[0], 0), num(center[1], 0), num(center[2], 0)],
      size: [num(size[0], 20), num(size[1], 20), num(size[2], 20)],
    }),
    [center, size],
  )

  const receptorUrl = selectedReceptorId ? dockingReceptorFileUrl(selectedReceptorId) : null
  const poseUrl = activePose ? dockingPoseUrl(activePose.pose_id) : null
  const contextHint = useMemo(() => {
    const parts = []
    if (activeReceptor) parts.push(`receptor=${activeReceptor.name} (${activeReceptor.receptor_id})`)
    if (selectedJobId) parts.push(`job=${selectedJobId}`)
    parts.push(`box center=${box.center.join(',')} size=${box.size.join(',')}`)
    return parts.join('; ')
  }, [activeReceptor, selectedJobId, box])

  const handleUpload = async (file: File) => {
    setUploadPercent(0)
    try {
      const result = await uploadMutation.mutateAsync({
        file,
        name: uploadName || file.name.replace(/\.pdb$/i, ''),
        onProgress: setUploadPercent,
      })
      setSelectedReceptorId(result.receptor.receptor_id)
      setUploadName('')
      showToast(t('docking.receptorUploaded', { name: result.receptor.name }), 'success')
    } catch (error) {
      showToast(getUserFacingError(error, t('common.unknownError')), 'error')
    } finally {
      setUploadPercent(null)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleRun = async () => {
    if (!selectedReceptorId) {
      showToast(t('docking.needReceptor'), 'error')
      return
    }
    const ligands = parseLigands(ligandsText)
    if (ligands.length === 0) {
      showToast(t('docking.needLigands'), 'error')
      return
    }
    try {
      const result = await createJob.mutateAsync({
        receptor_id: selectedReceptorId,
        ligands,
        box,
        params: {
          search_mode: searchMode,
          scoring,
          exhaustiveness: num(exhaustiveness, 8),
          num_modes: num(numModes, 9),
          seed: num(seed, 0),
        },
      })
      setSelectedJobId(result.job.job_id)
      setSelectedPoseId(null)
      showToast(t('docking.jobQueued'), 'success')
    } catch (error) {
      showToast(getUserFacingError(error, t('common.unknownError')), 'error')
    }
  }

  return (
    <PageContainer className="docking-page" noPadding>
      <div className="docking-toolbar">
        <TargetIcon size={16} />
        <span className="docking-toolbar__title">{t('docking.title')}</span>
        <span className="docking-status">
          <span className={`docking-status__dot${engine.data?.ready ? ' is-ready' : ''}`} aria-hidden="true" />
          {engine.data?.ready
            ? t('docking.engineReady', { engine: engine.data.engine })
            : t('docking.engineUnavailable')}
        </span>
      </div>

      <div className="docking-workbench">
        {/* ── Left: inputs & parameters ─────────────────────────────── */}
        <ScrollColumn className="docking-pane docking-pane--left">
          <section className="docking-group">
            <h2 className="docking-group__title">{t('docking.receptor')}</h2>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdb"
              className="docking-file"
              aria-label={t('docking.uploadReceptor')}
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void handleUpload(file)
              }}
            />
            <Input
              value={uploadName}
              onChange={(event) => setUploadName(event.target.value)}
              placeholder={t('docking.receptorName')}
            />
            {uploadPercent !== null && <ProgressBar value={uploadPercent} showPercent height={6} />}
            <ul className="docking-list">
              {receptorList.map((receptor) => (
                <li key={receptor.receptor_id}>
                  <button
                    type="button"
                    className={`docking-list__row${receptor.receptor_id === selectedReceptorId ? ' is-active' : ''}`}
                    onClick={() => setSelectedReceptorId(receptor.receptor_id)}
                  >
                    <span className="docking-list__name">{receptor.name}</span>
                    <span className="docking-list__meta">{receptor.source_filename}</span>
                  </button>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<TrashIcon size={14} />}
                    ariaLabel={t('common.delete')}
                    onClick={() => void deleteMutation.mutateAsync(receptor.receptor_id)}
                  />
                </li>
              ))}
            </ul>
          </section>

          <section className="docking-group">
            <h2 className="docking-group__title">{t('docking.ligands')}</h2>
            <TextArea
              value={ligandsText}
              onChange={(event) => setLigandsText(event.target.value)}
              placeholder={t('docking.ligandsPlaceholder')}
              ariaLabel={t('docking.ligands')}
              rows={4}
              maxHeight={160}
            />
          </section>

          <section className="docking-group">
            <h2 className="docking-group__title">{t('docking.box')}</h2>
            <div className="docking-box-grid">
              {(['x', 'y', 'z'] as const).map((axis, index) => (
                <label key={`c-${axis}`} className="docking-field">
                  <span>{t('docking.center')} {axis.toUpperCase()}</span>
                  <Input value={center[index]} onChange={(e) => setCenter(center.map((v, i) => i === index ? e.target.value : v))} type="number" />
                </label>
              ))}
              {(['x', 'y', 'z'] as const).map((axis, index) => (
                <label key={`s-${axis}`} className="docking-field">
                  <span>{t('docking.size')} {axis.toUpperCase()}</span>
                  <Input value={size[index]} onChange={(e) => setSize(size.map((v, i) => i === index ? e.target.value : v))} type="number" />
                </label>
              ))}
            </div>
          </section>

          <section className="docking-group">
            <h2 className="docking-group__title">{t('docking.params')}</h2>
            <div className="docking-box-grid">
              <label className="docking-field">
                <span>{t('docking.exhaustiveness')}</span>
                <Input value={exhaustiveness} onChange={(e) => setExhaustiveness(e.target.value)} type="number" />
              </label>
              <label className="docking-field">
                <span>{t('docking.numModes')}</span>
                <Input value={numModes} onChange={(e) => setNumModes(e.target.value)} type="number" />
              </label>
              <label className="docking-field">
                <span>{t('docking.seed')}</span>
                <Input value={seed} onChange={(e) => setSeed(e.target.value)} type="number" />
              </label>
              <label className="docking-field">
                <span>{t('docking.searchMode')}</span>
                <Select
                  value={searchMode}
                  onChange={setSearchMode}
                  showPlaceholder={false}
                  ariaLabel={t('docking.searchMode')}
                  options={[
                    { value: 'fast', label: 'fast' },
                    { value: 'balance', label: 'balance' },
                    { value: 'detail', label: 'detail' },
                  ]}
                />
              </label>
              <label className="docking-field">
                <span>{t('docking.scoring')}</span>
                <Select
                  value={scoring}
                  onChange={setScoring}
                  showPlaceholder={false}
                  ariaLabel={t('docking.scoring')}
                  options={[
                    { value: 'vina', label: 'vina' },
                    { value: 'vinardo', label: 'vinardo' },
                    { value: 'ad4', label: 'ad4' },
                  ]}
                />
              </label>
            </div>
          </section>

          <Button variant="primary" onClick={() => void handleRun()} loading={createJob.isPending}>
            {t('docking.run')}
          </Button>

          <section className="docking-group">
            <h2 className="docking-group__title">{t('docking.jobs')}</h2>
            <ul className="docking-list">
              {jobList.map((item) => (
                <li key={item.job_id}>
                  <button
                    type="button"
                    className={`docking-list__row${item.job_id === selectedJobId ? ' is-active' : ''}`}
                    onClick={() => { setSelectedJobId(item.job_id); setSelectedPoseId(null) }}
                  >
                    <span className="docking-list__name">{item.engine}</span>
                    <span className="docking-list__meta">{item.status}</span>
                  </button>
                  {(item.status === 'pending' || item.status === 'running') && (
                    <Button variant="ghost" size="sm" onClick={() => void cancelJob.mutateAsync(item.job_id)}>
                      {t('docking.cancel')}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </ScrollColumn>

        {/* ── Center: 3D structure ──────────────────────────────────── */}
        <div className="docking-pane docking-pane--center">
          <StructureViewer3D
            receptorUrl={receptorUrl}
            poseUrl={poseUrl}
            box={box}
            ariaLabel={t('docking.viewer')}
          />
          {job && (
            <div className="docking-poses">
              {job.status === 'failed' && <InlineAlert tone="danger">{job.error}</InlineAlert>}
              {poses.map((pose) => (
                <button
                  key={pose.pose_id}
                  type="button"
                  className={`docking-pose${pose.pose_id === selectedPoseId ? ' is-active' : ''}`}
                  onClick={() => setSelectedPoseId(pose.pose_id)}
                >
                  <span>{pose.ligand_label}</span>
                  <span className="docking-pose__affinity">
                    {pose.affinity != null ? `${pose.affinity.toFixed(2)} kcal/mol` : '—'}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* ── Right: agent ──────────────────────────────────────────── */}
        <div className="docking-pane docking-pane--right">
          <DockingAgentPanel contextHint={contextHint} />
        </div>
      </div>
    </PageContainer>
  )
}
