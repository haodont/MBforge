import DescItem from './DescItem'

export interface ChemDescriptors {
  molecular_weight: number
  logp: number
  tpsa: number
  hba: number
  hbd: number
  rotatable_bonds: number
  formula: string
}

interface Props {
  descriptors: ChemDescriptors | null
  loading: boolean
}

export default function DescGrid({ descriptors, loading }: Props) {
  if (loading) {
    return (
      <div
        style={{
          gridColumn: '1 / -1',
          textAlign: 'center',
          padding: 16,
          color: 'var(--text-muted)',
          fontSize: 13,
        }}
      >
        正在计算…
      </div>
    )
  }
  if (!descriptors) {
    return (
      <div
        style={{
          gridColumn: '1 / -1',
          textAlign: 'center',
          padding: 16,
          color: 'var(--text-muted)',
          fontSize: 13,
        }}
      >
        无法计算理化性质
      </div>
    )
  }
  return (
    <>
      <DescItem label="分子式" value={descriptors.formula} />
      <DescItem label="分子量" value={descriptors.molecular_weight.toFixed(1)} unit="g/mol" />
      <DescItem label="脂溶性" value={descriptors.logp.toFixed(2)} unit="LogP" />
      <DescItem label="极性表面积" value={descriptors.tpsa.toFixed(1)} unit="Å²" />
      <DescItem label="氢键受体" value={String(descriptors.hba)} unit="HBA" />
      <DescItem label="氢键供体" value={String(descriptors.hbd)} unit="HBD" />
    </>
  )
}