import { httpGet } from './_utils'

export interface DocPageSummary { slug: string; title: string }
export interface DocsIndexResponse { pages: DocPageSummary[] }
export interface DocPage extends DocPageSummary { content: string }

export function listDocsPages(): Promise<DocsIndexResponse> {
  return httpGet<DocsIndexResponse>('/docs/pages')
}

export function getDocsPage(slug: string): Promise<DocPage> {
  return httpGet<DocPage>(`/docs/pages/${encodeURIComponent(slug)}`)
}
