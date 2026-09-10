import { useState, useEffect, useRef, useCallback } from 'react'
import { smilesToRdkitSvg } from '@/api/http/molecule'
import { Editor } from 'ketcher-react'
import { StandaloneStructServiceProvider } from 'ketcher-standalone'
import 'ketcher-react/dist/index.css'
import Button from '@/components/ui/Button'
import IconButton from '@/components/ui/IconButton'
import Input from '@/components/ui/Input'
import { XIcon } from '../icons'
import ScrollColumn from '@/components/ui/ScrollColumn'

const structServiceProvider = new StandaloneStructServiceProvider()

interface MoleculeEditorDialogProps {
  smiles: string
  name?: string
  /** 原始文献中的分子裁剪图；存在时优先于 RDKit 重新绘图。 */
  originalImageUrl?: string | null
  onSave: (newSmiles: string, newName?: string) => void | Promise<void>
  onClose: () => void
}

/**
 * 分子交互式编辑浮窗
 *
 * 直接使用 Ketcher 编辑器，支持：
 * - 可视化绘图编辑
 * - 导出 SMILES
 * - 原始文献分子图预览
 * - 无原始图片时使用 RDKit 结构图预览（支持 Markush `*` 原子）
 * - 保存覆盖原数据
 */
export default function MoleculeEditorDialog({
  smiles,
  name,
  originalImageUrl,
  onSave,
  onClose,
}: MoleculeEditorDialogProps) {
interface KetcherInstance {
  setMolecule: (smiles: string) => Promise<void>
  getSmiles: () => Promise<string>
}

  const ketcherRef = useRef<KetcherInstance | null>(null)
  const [saving, setSaving] = useState(false)
  const [currentSmiles, setCurrentSmiles] = useState(smiles)
  const [currentName, setCurrentName] = useState(name ?? '')
  const [rdkitSvg, setRdkitSvg] = useState<string | null>(null)
  const [renderError, setRenderError] = useState<string | null>(null)
  const [renderLoading, setRenderLoading] = useState(false)
  const [originalImageFailed, setOriginalImageFailed] = useState(false)

  useEffect(() => {
    setOriginalImageFailed(false)
  }, [originalImageUrl])

  useEffect(() => {
    setCurrentName(name ?? '')
  }, [name])

  // Ketcher 初始化后加载 SMILES
  const handleInit = useCallback((ketcher: KetcherInstance) => {
    ketcherRef.current = ketcher
    if (smiles) {
      ketcher.setMolecule(smiles).catch(() => {
        if (import.meta.env.DEV) console.warn('Failed to load SMILES into Ketcher')
      })
    }
  }, [smiles])

  // 获取当前 SMILES 并更新 MoleCode
  const handleGetFromKetcher = useCallback(async () => {
    if (!ketcherRef.current) return
    try {
      const newSmiles = await ketcherRef.current.getSmiles()
      if (newSmiles) {
        setCurrentSmiles(newSmiles)
      }
    } catch (err) {
      console.error('Failed to get SMILES from Ketcher:', err)
    }
  }, [])

  // SMILES 变化时由本地 RDKit 生成结构图，支持 `*` 等 Markush 占位符。
  useEffect(() => {
    if (!currentSmiles.trim()) return
    setRenderLoading(true)
    setRdkitSvg(null)
    setRenderError(null)
    smilesToRdkitSvg(currentSmiles)
      .then(setRdkitSvg)
      .catch((error: unknown) => {
        setRenderError(error instanceof Error ? error.message : 'RDKit 无法渲染此结构')
      })
      .finally(() => setRenderLoading(false))
  }, [currentSmiles])

  // 保存
  const handleSave = useCallback(async () => {
    if (!ketcherRef.current) return
    setSaving(true)
    try {
      const newSmiles = await ketcherRef.current.getSmiles()
      if (newSmiles) {
        await onSave(newSmiles, currentName.trim())
      }
      onClose()
    } catch (err) {
      console.error('Failed to get SMILES from Ketcher:', err)
    } finally {
      setSaving(false)
    }
  }, [currentName, onSave, onClose])

  // Escape closes the dialog; Tab/Shift+Tab is trapped inside the
  // dialog so keyboard users cannot tab into underlying UI.
  const containerRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    const container = containerRef.current
    // Move focus into the dialog on mount.
    const firstFocusable = container?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    )
    firstFocusable?.focus()

    const focusableSelector =
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key !== 'Tab' || !container) return
      const focusables = Array.from(
        container.querySelectorAll<HTMLElement>(focusableSelector),
      ).filter((el) => !el.hasAttribute('aria-hidden'))
      if (focusables.length === 0) {
        e.preventDefault()
        return
      }
      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      const active = document.activeElement as HTMLElement | null
      if (e.shiftKey) {
        if (active === first || !container.contains(active)) {
          e.preventDefault()
          last.focus()
        }
      } else {
        if (active === last || !container.contains(active)) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown, true)
    return () => {
      window.removeEventListener('keydown', handleKeyDown, true)
      previouslyFocused?.focus()
    }
  }, [onClose])

  return (
    <div
      ref={containerRef}
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        style={{
          background: 'var(--bg-surface)',
          borderRadius: 12,
          width: '90vw',
          maxWidth: 1200,
          height: '85vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
        }}
      >
        {/* 标题栏 */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 16px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--bg-elevated)',
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600 }}>
            分子编辑器 {name && `- ${name}`}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button size="sm" variant="primary" onClick={handleSave} loading={saving} disabled={saving}>
              {saving ? '保存中...' : '保存'}
            </Button>
            <IconButton size={32} onClick={onClose} ariaLabel="关闭" title="关闭">
              <XIcon size={14} />
            </IconButton>
          </div>
        </div>

        {/* 主内容区 */}
        <div style={{ flex: 1, display: 'flex', minWidth: 0, minHeight: 0, overflow: 'hidden' }}>
          {/* 左侧：Ketcher 编辑器 */}
          <div style={{ flex: '2 1 0', minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)', overflow: 'hidden', position: 'relative', isolation: 'isolate' }}>
            <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflow: 'hidden' }}>
              <Editor
                staticResourcesUrl="/ketcher"
                structServiceProvider={structServiceProvider}
                onInit={handleInit}
                errorHandler={(msg: string) => console.error('Ketcher:', msg)}
              />
            </div>
            {/* 从画布获取按钮 */}
            <div style={{ padding: '8px 12px', borderTop: '1px solid var(--border)' }}>
            <Button size="sm" variant="secondary" onClick={handleGetFromKetcher}>
              ← 从画布获取 SMILES
            </Button>
            </div>
          </div>

          {/* 右侧：优先显示原始文献图片，无图片时回退到 RDKit */}
          <div style={{ flex: '1 1 0', minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative', zIndex: 1, background: 'var(--bg-surface)' }}>
            <div style={{ flexShrink: 0, padding: '12px 16px 8px', borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', textWrap: 'balance' }}>
                {originalImageUrl && !originalImageFailed ? '原始图片预览' : '结构预览'}
              </div>
            </div>
            <ScrollColumn padding="12px 16px">
              <div
                style={{
                  background: 'var(--bg-base)',
                  border: '1px solid var(--border)',
                  padding: 10,
                  borderRadius: 6,
                  margin: 0,
                  minHeight: 240,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {originalImageUrl && !originalImageFailed ? (
                  <img
                    src={originalImageUrl}
                    alt="文献中的原始分子图"
                    onError={() => setOriginalImageFailed(true)}
                    style={{ width: '100%', maxHeight: 320, objectFit: 'contain', outline: '1px solid rgba(0, 0, 0, 0.1)', borderRadius: 4, background: '#fff' }}
                  />
                ) : renderLoading ? '正在生成结构图…' : rdkitSvg ? (
                  <img
                    src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(rdkitSvg)}`}
                    alt="当前 E-SMILES 的 RDKit 结构图"
                    style={{ width: '100%', maxHeight: 320, objectFit: 'contain', outline: '1px solid rgba(0, 0, 0, 0.1)', borderRadius: 4 }}
                  />
                ) : (
                  <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{renderError ?? '无法生成结构图'}</span>
                )}
              </div>
              <div style={{ marginTop: 12 }}>
                <label htmlFor="molecule-editor-name" style={{ display: 'block', marginBottom: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
                  分子 ID / 标签
                </label>
                <Input
                  id="molecule-editor-name"
                  ariaLabel="分子 ID / 标签"
                  value={currentName}
                  onChange={(event) => setCurrentName(event.target.value)}
                  placeholder="如 1d"
                  style={{ width: '100%', minHeight: 40 }}
                />
              </div>
            </ScrollColumn>
          </div>
        </div>
      </div>
    </div>
  )
}
