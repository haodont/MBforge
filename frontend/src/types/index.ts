export interface Message {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface Project {
  name: string
  root: string
  document_count: number
  molecule_count: number
}

export interface DocumentEntry {
  doc_id: string
  path: string
  source_path?: string | null
  doc_type: string
  title: string
  folder?: string
  added_at?: string
  hash?: string
  mtime?: number
  inspector_status?: string
  text_status?: string
  ocr_status?: string
  ocr_hash?: string
  moldet_status?: string
  moldet_pages?: number[]
}

export interface SearchResult {
  id: string
  text: string
  metadata: Record<string, unknown>
  distance: number
}

export interface MoleculeRecord {
  mol_id: string
  /** Canonical SMILES (RDKit-validated). */
  smiles?: string
  /** Extended SMILES (raw extracted, may contain Markush wildcards). */
  esmiles: string
  name: string
  source_doc: string
  source_type: string
  activity: number | null
  activity_type: string
  units: string
  status: string
  properties: Record<string, unknown>
  tags: string[]
  notes: string
  created_at: string
  /** Evidence chain populated by the /api/v1/molecule/list and /evidence endpoints. */
  evidence?: EvidenceItem[]
  /** Total evidence count (when list view truncates). */
  evidence_total?: number
}

/** One entry in a molecule's evidence chain (figure / text / table kind). */
export interface EvidenceItem {
  id: number
  doc_id: string
  page: number | null
  /** Bounding box in PDF point units; null for text/table kind. */
  bbox: { x0: number; y0: number; x1: number; y1: number } | null
  /** Server-built URL the frontend can use as <img src>. */
  crop_url: string | null
  context_text: string | null
  code_text: string | null
  role: string
  kind: 'figure' | 'text' | 'table'
  confidence: number | null
  source_type: string | null
  created_at: string | null
}


export interface ModelStatus {
  status: 'ready' | 'loading' | 'error' | 'offline'
}

export interface HealthResponse {
  status: string
  models: Record<string, string>
  error: string | null
}

export interface FileNode {
  name: string
  path: string
  is_dir: boolean
  children: FileNode[]
}

export interface ChatMessage {
  id?: string
  role: string
  content: string
  timestamp?: string
}

// ---- MolDet 分子检测结果 ----

/** MolDet 检测结果（与后端 ExtractionResult 对齐） */
export interface ExtractionResult {
  evidence_id?: string
  esmiles: string
  smiles?: string
  name: string
  source: 'image' | 'text' | 'manual'
  moldet_conf: number
  bbox_pdf: [number, number, number, number] | null  // [x1, y1, x2, y2] PDF points
  page_idx: number | null
  context_text: string
  mol_img_path: string | null
  status: 'pending' | 'confirmed' | 'rejected' | 'done'
  is_quick_scan?: boolean
  properties: Record<string, unknown>
}

/** 任务状态 */
export interface TaskState {
  status: 'idle' | 'parsing' | 'detecting' | 'completed' | 'error'
  progress: number       // 0-100
  currentPage: number
  totalPages: number
  error?: string
  startedAt?: number
  completedAt?: number
}

/** 模型状态 */
export type ModelStatusType = 'unknown' | 'ready' | 'loading' | 'error' | 'offline'

/** MolDet 检测框（像素坐标） */
export interface DetectionBox {
  x1: number
  y1: number
  x2: number
  y2: number
  conf: number
  result?: ExtractionResult
}

// ---- SAR 分析 ----

/** 单个分子实体（用于 SAR 表）*/
export interface SARCompound {
  id: string
  esmiles: string
  /** 化合物名称 / 编号 */
  name: string
  /** R-group 取代基位置（以原子索引为 key）*/
  rGroups: Record<number, string>
  /** 活性数据 */
  activity?: number
  /** 活性类型（IC50 / EC50 / Ki ...）*/
  activityType?: string
  /** 单位（nM / uM ...）*/
  units?: string
  /** 选择性数据 */
  selectivity?: Record<string, number>
  /** 备注 */
  notes?: string
}

/** SAR 分析会话 */
export interface SARSession {
  id: string
  /** 课题名称 */
  name: string
  /** 靶点 / 蛋白 */
  target?: string
  /** 化合物列表 */
  compounds: SARCompound[]
  /** 核心骨架 SMILES（用于 R-group 分析）*/
  coreSmiles?: string
  /** 关联的文献 */
  sourceDocs?: string[]
  /** 创建时间 */
  createdAt: string
}


// ---- DocumentReport (EVT_DOC_RESULT payload) ----

/** 化合物（与 Rust `CompoundEntry` 对应）*/
export interface CompoundEntry {
  name: string
  /** ESMILES 字符串（optional） */
  esmiles?: string | null
  /** 类别（lead / hit / reference / intermediate） */
  category?: string | null
  description: string
  /** 缩写 / 代号（Dagdelen 2024 spirit） */
  acronym?: string | null
  /** 晶系 / 结构（cubic / Fd3m / layered ...）*/
  structure_or_phase?: string[]
  source_ref: string
  confidence: 'high' | 'medium' | 'low'
  uncertainty_reason?: string | null
}

/** 活性数据条目 */
export interface ActivityEntry {
  compound: string
  activity_type: string
  value: number
  units: string
  target?: string | null
  source_quote: string
  source_ref: string
  confidence: 'high' | 'medium' | 'low'
}

/** 关键发现 */
export interface FindingEntry {
  finding: string
  evidence: string
  source_ref: string
  confidence: 'high' | 'medium' | 'low'
}

/** 不确定项 */
export interface UncertainItem {
  item_type: 'compound' | 'activity' | 'finding' | 'classification'
  content: string
  reason: string
  suggested_action: string
}

/** 文档元数据 */
export interface DocumentMetadata {
  title?: string | null
  authors: string[]
  document_type: string
  key_targets: string[]
  source_file?: string | null
}

/** EVT_DOC_RESULT 事件 payload — Rust `DocumentReport` */
export interface DocumentReport {
  metadata: DocumentMetadata
  compounds: CompoundEntry[]
  activities: ActivityEntry[]
  key_findings: FindingEntry[]
  sar_analysis: string
  uncertain_items: UncertainItem[]
  report_markdown: string
  /** LiteratureAgent 二次审阅标志（[方案 3]）*/
  lit_reviewed: boolean
  /** LitAgent 决策摘要 */
  lit_decision_summary?: string | null
}
