/** Docking API — receptors, jobs, poses (manual + agent share these). */

import { apiUrl, httpGet, httpPost, httpDelete, invokeWithError } from './_utils'

export interface DockingReceptor {
  receptor_id: string
  name: string
  source_filename: string
  pdbqt_path: string
  file_hash: string
  chain: string
  meta: Record<string, unknown>
  created_at: string
}

export interface DockingBox {
  center: number[]
  size: number[]
}

export interface DockingLigandInput {
  label?: string
  smiles: string
  mol_id?: string | null
}

export interface DockingPose {
  pose_id: string
  job_id: string
  mol_id: string | null
  ligand_label: string
  affinity: number | null
  rmsd_lb: number | null
  rmsd_ub: number | null
  rank: number
  pose_path: string
  created_at: string
}

export interface DockingJob {
  job_id: string
  receptor_id: string
  engine: string
  params: Record<string, unknown>
  box: DockingBox
  ligands: DockingLigandInput[]
  status: string
  progress: number
  message: string
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  poses?: DockingPose[]
}

export interface EngineStatus {
  success: boolean
  ready: boolean
  engine: string
  reason: string
}

export async function fetchEngineStatus(): Promise<EngineStatus> {
  return invokeWithError(() => httpGet('/api/v1/docking/engine/status'))
}

export async function listReceptors(): Promise<{ receptors: DockingReceptor[] }> {
  return invokeWithError(() => httpGet('/api/v1/docking/receptors'))
}

export async function deleteReceptor(receptorId: string): Promise<{ success: boolean; deleted: number }> {
  return invokeWithError(() =>
    httpDelete(`/api/v1/docking/receptors/${encodeURIComponent(receptorId)}`),
  )
}

/** Upload a PDB and let the backend prepare the PDBQT (XHR for progress). */
export async function uploadReceptor(
  file: File,
  name: string,
  onProgress?: (percent: number) => void,
): Promise<{ success: boolean; receptor: DockingReceptor }> {
  const form = new FormData()
  form.append('file', file)
  form.append('name', name)

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', apiUrl('/api/v1/docking/receptors'))
    if (onProgress) {
      request.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
      }
    }
    request.onload = () => {
      let payload: unknown
      try {
        payload = JSON.parse(request.responseText)
      } catch (error) {
        reject(error instanceof Error ? error : new Error('Upload failed'))
        return
      }
      if (request.status >= 200 && request.status < 300) {
        resolve(payload as { success: boolean; receptor: DockingReceptor })
        return
      }
      const message = (payload as { error?: string }).error
      reject(new Error(message || `Upload failed (${request.status})`))
    }
    request.onerror = () => reject(new Error('Upload request failed'))
    request.send(form)
  })
}

export async function listDockingJobs(status = ''): Promise<{ jobs: DockingJob[] }> {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  return invokeWithError(() => httpGet(`/api/v1/docking/jobs${query}`))
}

export async function getDockingJob(jobId: string): Promise<{ job: DockingJob }> {
  return invokeWithError(() => httpGet(`/api/v1/docking/jobs/${encodeURIComponent(jobId)}`))
}

export async function createDockingJob(body: {
  receptor_id: string
  ligands: DockingLigandInput[]
  box: DockingBox
  params?: Record<string, unknown>
}): Promise<{ job: DockingJob }> {
  return invokeWithError(() => httpPost('/api/v1/docking/jobs', body as unknown as Record<string, unknown>))
}

export async function cancelDockingJob(jobId: string): Promise<{ job: DockingJob }> {
  return invokeWithError(() =>
    httpPost(`/api/v1/docking/jobs/${encodeURIComponent(jobId)}/cancel`, {}),
  )
}

export function dockingPoseUrl(poseId: string): string {
  return apiUrl(`/api/v1/docking/poses/${encodeURIComponent(poseId)}`)
}

export function dockingReceptorFileUrl(receptorId: string): string {
  return apiUrl(`/api/v1/docking/receptors/${encodeURIComponent(receptorId)}/file`)
}
