import { imageUrl } from '@/api/http/library'

export function cleanMoleculePlaceholders(markdown: string): string {
  return markdown
    .replace(/^\s*<!--\s*Molecule\s+([^>]+?)\s*-->\s*$/gim, '')
    // These are pipeline-internal placeholders, not useful document content.
    .replace(/```[^\n]*\n(?:MoleCode|Structure) not (?:available|generated) for [^\n]+\n```\s*/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export function rewriteImageUrls(
  markdown: string,
  docId: string,
  libraryRoot: string
): string {
  return markdown.replace(
    /!\[([^\]]*)\]\(images\/([^)]+)\)/g,
    (_match, alt: string, filename: string) => {
      const url = imageUrl(docId, filename, libraryRoot)
      return `![${alt}](${url})`
    }
  )
}
