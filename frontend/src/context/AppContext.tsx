import {
  createContext,
  useContext,
  useState,
  useReducer,
  useCallback,
  type ReactNode,
} from 'react'
import type { DocumentEntry, PdfSidePaneTab } from '../types'

// ============================================================================
// ActiveFile — 跨组件文件导航请求（侧边栏文件树 → ProjectView）
// ============================================================================

export interface ActiveFile {
  path: string
  type: 'pdf' | 'markdown'
  mode?: string
}

// ============================================================================
// Tab — 标签栏打开的文件/视图
// ============================================================================

export interface Tab {
  id: string
  type: 'pdf' | 'markdown' | 'document'
  title: string
  doc: DocumentEntry
  libraryRoot: string
  /** Optional 1-based PDF deep-link target. */
  initialPage?: number
  /** Optional PDF-point bbox deep-link target. */
  initialBbox?: [number, number, number, number]
  /** Optional canonical source-evidence id to highlight on open. */
  initialEvidenceId?: string
  /** Optional result pane to select when opening the document. */
  initialSidePaneTab?: PdfSidePaneTab
  /** Changes on every explicit pane navigation, including an already-open tab. */
  sidePaneRequestId?: string
}

let _tabIdSeq = 0
function nextTabId(): string {
  _tabIdSeq += 1
  return `tab-${_tabIdSeq}-${Date.now()}`
}

interface TabsState {
  openTabs: Tab[]
  activeTabId: string | null
}

type TabsAction =
  | { type: 'open'; tab: Omit<Tab, 'id' | 'sidePaneRequestId'>; id: string }
  | { type: 'close'; tabId: string }
  | { type: 'set-active'; tabId: string | null }
  | { type: 'reset' }

const initialTabsState: TabsState = { openTabs: [], activeTabId: null }

function tabsReducer(state: TabsState, action: TabsAction): TabsState {
  switch (action.type) {
    case 'open': {
      const existing = state.openTabs.find(
        tab => tab.type === action.tab.type && tab.doc.doc_id === action.tab.doc.doc_id,
      )
      if (existing) {
        const hasLocation = action.tab.initialPage !== undefined || action.tab.initialBbox !== undefined || action.tab.initialEvidenceId !== undefined
        const hasSidePaneRequest = action.tab.initialSidePaneTab !== undefined
        return {
          ...state,
          openTabs: hasLocation || hasSidePaneRequest
            ? state.openTabs.map(tab => tab.id === existing.id
              ? {
                  ...tab,
                  initialPage: action.tab.initialPage ?? tab.initialPage,
                  initialBbox: action.tab.initialBbox ?? tab.initialBbox,
                  initialEvidenceId: action.tab.initialEvidenceId ?? tab.initialEvidenceId,
                  initialSidePaneTab: action.tab.initialSidePaneTab ?? tab.initialSidePaneTab,
                  sidePaneRequestId: hasSidePaneRequest ? action.id : tab.sidePaneRequestId,
                }
              : tab)
            : state.openTabs,
          activeTabId: existing.id,
        }
      }

      return {
        openTabs: [...state.openTabs, {
          ...action.tab,
          id: action.id,
          sidePaneRequestId: action.tab.initialSidePaneTab === undefined ? undefined : action.id,
        }],
        activeTabId: action.id,
      }
    }
    case 'close': {
      const index = state.openTabs.findIndex(tab => tab.id === action.tabId)
      if (index === -1) return state

      const openTabs = state.openTabs.filter(tab => tab.id !== action.tabId)
      if (state.activeTabId !== action.tabId) return { ...state, openTabs }
      if (openTabs.length === 0) return { openTabs, activeTabId: null }

      return {
        openTabs,
        activeTabId: openTabs[Math.min(index, openTabs.length - 1)].id,
      }
    }
    case 'set-active':
      return {
        ...state,
        activeTabId: action.tabId === null || state.openTabs.some(tab => tab.id === action.tabId)
          ? action.tabId
          : null,
      }
    case 'reset':
      return initialTabsState
  }
}

// ============================================================================
// AppState
// ============================================================================

interface AppState {
  /** Library root directory (canonical) */
  libraryRoot: string
  /** Set library root (persists to localStorage) */
  setLibraryRoot: (root: string) => void
  researchDocumentIds: string[]
  setResearchDocumentIds: React.Dispatch<React.SetStateAction<string[]>>
  /** 通过全局文件树选中的待打开文件 */
  activeFile: ActiveFile | null
  /** 设置待打开文件（ProjectView 消费后应置空） */
  setActiveFile: (file: ActiveFile | null) => void

  // --- 标签栏 ---
  /** 结果工作区中打开的文件标签。 */
  openTabs: Tab[]
  /** 当前文件标签 ID；null 显示资源路由或研究首页。 */
  activeTabId: string | null
  /** 打开一个文件标签。如果已存在则激活它 */
  openTab: (tab: Omit<Tab, 'id' | 'sidePaneRequestId'>) => void
  /** 关闭一个标签。如果关闭的是激活标签，自动激活相邻标签 */
  closeTab: (tabId: string) => void
  /** 激活指定文件；null 返回资源路由。 */
  setActiveTabId: (tabId: string | null) => void

}

const AppContext = createContext<AppState | null>(null)

// ============================================================================
// AppProvider
// ============================================================================

export function AppProvider({ children }: { children: ReactNode }) {
  // The backend is the single source of truth for the library root.
  // App.tsx reconciles any persisted localStorage value by calling
  // getLibraryStatus() on mount and setting the root from the server.
  const [libraryRoot, setLibraryRootState] = useState('')
  const [researchDocumentIds, setResearchDocumentIds] = useState<string[]>([])

  const [activeFile, setActiveFile] = useState<ActiveFile | null>(null)
  const [{ openTabs, activeTabId }, dispatchTabs] = useReducer(tabsReducer, initialTabsState)

  const setLibraryRoot = useCallback((root: string) => {
    setLibraryRootState(root)
    setResearchDocumentIds([])
    dispatchTabs({ type: 'reset' })
  }, [])

  const openTab = useCallback((tab: Omit<Tab, 'id'>) => {
    dispatchTabs({ type: 'open', tab, id: nextTabId() })
  }, [])

  const closeTab = useCallback((tabId: string) => {
    dispatchTabs({ type: 'close', tabId })
  }, [])

  const setActiveTabId = useCallback((tabId: string | null) => {
    dispatchTabs({ type: 'set-active', tabId })
  }, [])

  return (
    <AppContext.Provider
      value={{
        libraryRoot,
        setLibraryRoot,
        researchDocumentIds,
        setResearchDocumentIds,
        activeFile,
        setActiveFile,
        openTabs,
        activeTabId,
        openTab,
        closeTab,
        setActiveTabId,
      }}
    >
      {children}
    </AppContext.Provider>
  )
}

/** 获取 App 全局状态。必须在 AppProvider 内部使用。 */
export function useAppContext(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) {
    throw new Error('useAppContext must be used within <AppProvider>')
  }
  return ctx
}

/** Read app navigation state from leaf components that also have standalone tests. */
export function useOptionalAppContext(): AppState | null {
  return useContext(AppContext)
}
