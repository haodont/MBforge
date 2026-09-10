/** Science icons. */

import type { FC } from 'react'
import { baseSvg, type IconProps } from './types'

export const FlaskIcon: FC<IconProps> = ({ size = 20 }) =>
  baseSvg(
    <>
      <path d="M9 3h6v5l4 11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L9 8V3" />
      <line x1="9" y1="3" x2="15" y2="3" />
      <line x1="7" y1="14" x2="17" y2="14" />
    </>,
    size,
  )

export const BeakerIcon: FC<IconProps> = ({ size = 18 }) =>
  baseSvg(
    <>
      <path d="M9 3h6" />
      <path d="M10 3v6L4 19a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-6-10V3" />
      <path d="M7 15h10" />
    </>,
    size,
  )

export const BookIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </>,
    size,
  )

export const SparklesIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5L12 3z" />
      <path d="M18 15l-1 2.5L14.5 18l2.5 1 1 2.5 1-2.5L22 18l-2.5-1L18 15z" />
    </>,
    size,
  )

export const TargetIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="6" />
      <circle cx="12" cy="12" r="2" />
    </>,
    size,
  )

export const BarChartIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </>,
    size,
  )

export const ClusterIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <circle cx="8" cy="8" r="4" />
      <circle cx="16" cy="12" r="4" />
      <circle cx="8" cy="18" r="4" />
      <line x1="11" y1="10" x2="12.5" y2="10.5" />
      <line x1="12" y1="14" x2="12.5" y2="13" />
    </>,
    size,
  )

export const NetworkIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <circle cx="7" cy="4" r="2" />
      <circle cx="17" cy="4" r="2" />
      <circle cx="7" cy="20" r="2" />
      <circle cx="17" cy="20" r="2" />
      <line x1="9" y1="5" x2="15" y2="5" />
      <line x1="7" y1="6" x2="7" y2="18" />
      <line x1="17" y1="6" x2="17" y2="18" />
      <line x1="9" y1="19" x2="15" y2="19" />
    </>,
    size,
  )

export const FilterIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <polygon points="3 5 12 14 12 20 15 20 15 14 21 5" />
    </>,
    size,
  )

export const EmbedIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <circle cx="8" cy="8" r="3" />
      <circle cx="18" cy="8" r="3" />
      <circle cx="13" cy="18" r="3" />
      <line x1="10.5" y1="9.5" x2="15.5" y2="15.5" />
      <line x1="17" y1="10" x2="14" y2="15" />
      <line x1="10.5" y1="14.5" x2="10" y2="15" />
      <line x1="17" y1="6" x2="17" y2="5" />
    </>,
    size,
  )