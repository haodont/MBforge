/** React Query hooks for molecular docking. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  cancelDockingJob,
  createDockingJob,
  deleteReceptor,
  fetchEngineStatus,
  getDockingJob,
  listDockingJobs,
  listReceptors,
  uploadReceptor,
  type DockingBox,
  type DockingLigandInput,
} from '../../http/docking'
import { queryKeys } from '../keys'

/** Poll cadence while a job is not in a terminal state. */
const RUNNING_POLL_MS = 2000

function isActive(status: string | undefined): boolean {
  return status === 'pending' || status === 'running'
}

export function useDockingEngine() {
  return useQuery({ queryKey: queryKeys.docking.engine(), queryFn: fetchEngineStatus })
}

export function useReceptors() {
  return useQuery({ queryKey: queryKeys.docking.receptors(), queryFn: listReceptors })
}

export function useDockingJobs(status = '') {
  return useQuery({
    queryKey: queryKeys.docking.jobs(status),
    queryFn: () => listDockingJobs(status),
    refetchInterval: (query) =>
      (query.state.data?.jobs ?? []).some((job) => isActive(job.status)) ? RUNNING_POLL_MS : false,
  })
}

export function useDockingJob(jobId: string | null) {
  return useQuery({
    queryKey: queryKeys.docking.job(jobId ?? ''),
    queryFn: () => getDockingJob(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (query) => (isActive(query.state.data?.job.status) ? RUNNING_POLL_MS : false),
  })
}

export function useUploadReceptor() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, name, onProgress }: { file: File; name: string; onProgress?: (p: number) => void }) =>
      uploadReceptor(file, name, onProgress),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.docking.receptors() })
    },
  })
}

export function useDeleteReceptor() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (receptorId: string) => deleteReceptor(receptorId),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.docking.receptors() })
    },
  })
}

export function useCreateDockingJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      receptor_id: string
      ligands: DockingLigandInput[]
      box: DockingBox
      params?: Record<string, unknown>
    }) => createDockingJob(body),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.docking.all })
    },
  })
}

export function useCancelDockingJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => cancelDockingJob(jobId),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.docking.all })
    },
  })
}
