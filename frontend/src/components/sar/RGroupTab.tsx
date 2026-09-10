import { AlertBanner } from '../ui'
import RGroupMatrix from './RGroupMatrix'
import type { SARSession, SARCompound } from '@/types'

interface RGroupTabProps {
  session: SARSession
  onSelectCompound?: (compound: SARCompound) => void
}

export default function RGroupTab({ session, onSelectCompound }: RGroupTabProps) {
  return (
    <div>
      <AlertBanner
        variant="info"
        message="R-Group 分析自动从化合物结构中提取共同骨架（MCS 算法），无需手动标记 R 取代基位置。IC50 数值越低表示活性越高。"
      />
      <RGroupMatrix
        compounds={session.compounds}
        coreSmiles={session.coreSmiles}
        lowerIsBetter
        onCompoundClick={onSelectCompound}
      />
    </div>
  )
}
