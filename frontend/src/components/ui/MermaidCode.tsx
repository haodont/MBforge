import { useEffect, useId, useState } from 'react'
import mermaid from 'mermaid'
import DOMPurify from 'dompurify'
import { getUserFacingError } from '@/utils/errors'

// 初始化 mermaid（只执行一次）
let mermaidInitialized = false
function initMermaid() {
  if (mermaidInitialized) return
  mermaid.initialize({
    startOnLoad: false,
    theme: 'default',
    securityLevel: 'strict',
    fontFamily: 'monospace',
  })
  mermaidInitialized = true
}

interface MermaidCodeProps {
  code: string
  className?: string
}

/**
 * 渲染 Mermaid 图文本为 SVG
 *
 * 支持 MoleCode 格式的分子图（含缩写节点 {R1}、{Boc} 等）
 */
export function MermaidCode({ code, className }: MermaidCodeProps) {
  const uniqueId = useId()
  const [error, setError] = useState<string | null>(null)
  const [svg, setSvg] = useState<string>('')

  useEffect(() => {
    if (!code.trim()) return

    initMermaid()

    const renderMermaid = async () => {
      try {
        const id = `mermaid-${uniqueId.replace(/:/g, '')}`
        const { svg: renderedSvg } = await mermaid.render(id, code.trim())
        setSvg(DOMPurify.sanitize(renderedSvg, { USE_PROFILES: { svg: true } }))
        setError(null)
      } catch (err) {
        setError(getUserFacingError(err, 'Mermaid render failed'))
        setSvg('')
      }
    }

    void renderMermaid()
  }, [code, uniqueId])

  if (error) {
    return (
      <pre className={className} style={{ color: 'var(--text-secondary)', fontSize: 12, overflow: 'auto' }}>
        <code>{code}</code>
      </pre>
    )
  }

  if (!svg) {
    return (
      <div className={className} style={{ color: 'var(--text-secondary)', padding: 16, textAlign: 'center' }}>
        Loading...
      </div>
    )
  }

  return (
    <div
      className={className}
      style={{ overflow: 'auto' }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
