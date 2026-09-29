/** Canonical pipeline stage names, in execution order.
 *
 *  The registered backend pipeline is Extract → Markdown → Patent. This is the
 *  single source of the stage set for the frontend: import it instead of
 *  re-declaring the three names in each hook/component.
 */
export const PIPELINE_STAGES = ['extract', 'markdown', 'patent'] as const

export type PipelineStage = (typeof PIPELINE_STAGES)[number]
