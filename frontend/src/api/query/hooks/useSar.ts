/** React Query hooks for SAR analysis: activity cliffs, scaffold profile,
 *  R-group matrix construction, and the aggregated activity heatmap. */

import { useQuery } from '@tanstack/react-query'

import { molFindActivityCliffs, molScaffoldProfile } from '@/api/http/molecule_chem'
import type { ActivityCliff, ScaffoldProfile } from '@/api/http/molecule_chem'
import { sarBuildMatrix, sarHeatmap } from '@/api/http/sar'
import type { ActivityHeatmap, CompoundInput, RGroupMatrix } from '@/api/http/sar'
import { queryKeys } from '../keys'

/** Fail-closed R-group matrix envelope — the backend may report `success:false`. */
export type SarMatrixResponse = RGroupMatrix & { success?: boolean; error?: string }

/** Structure-similar / activity-divergent molecule pairs at the given thresholds. */
export function useActivityCliffs(
  libraryRoot: string | null,
  minSimilarity: number,
  minActivityRatio: number,
) {
  return useQuery<ActivityCliff[]>({
    queryKey: queryKeys.sar.cliffs(libraryRoot ?? '', minSimilarity, minActivityRatio),
    queryFn: () =>
      molFindActivityCliffs(libraryRoot as string, minSimilarity, minActivityRatio),
    enabled: Boolean(libraryRoot),
  })
}

/** Matched molecules + activity summary for a single query scaffold. */
export function useScaffoldProfile(
  libraryRoot: string | null,
  scaffoldEsmiles: string | null,
) {
  return useQuery<ScaffoldProfile>({
    queryKey: queryKeys.sar.scaffoldProfile(libraryRoot ?? '', scaffoldEsmiles ?? ''),
    queryFn: () => molScaffoldProfile(libraryRoot as string, scaffoldEsmiles as string),
    enabled: Boolean(libraryRoot && scaffoldEsmiles),
  })
}

/** Extract the common scaffold and build the compound × R-group matrix. */
export function useSarBuildMatrix(compounds: CompoundInput[], coreSmiles?: string) {
  return useQuery<SarMatrixResponse>({
    queryKey: queryKeys.sar.matrix(compounds, coreSmiles ?? ''),
    queryFn: () => sarBuildMatrix(compounds, coreSmiles),
    enabled: compounds.length >= 2,
  })
}

/** Aggregated activity heatmap for a built R-group matrix. */
export function useSarHeatmap(matrix: RGroupMatrix | null, lowerIsBetter = true) {
  return useQuery<ActivityHeatmap[]>({
    queryKey: queryKeys.sar.heatmap(matrix, lowerIsBetter),
    queryFn: () => sarHeatmap(matrix as RGroupMatrix, lowerIsBetter),
    enabled: Boolean(matrix),
  })
}
