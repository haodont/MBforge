/** Arrow icons. */

import type { FC } from 'react'
import { baseSvg, type IconProps } from './types'

export const ChevronRightIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <polyline points="9 18 15 12 9 6" />
    </>,
    size,
  )

export const ChevronLeftIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <polyline points="15 18 9 12 15 6" />
    </>,
    size,
  )

export const ArrowLeftIcon: FC<IconProps> = ({ size = 18 }) =>
  baseSvg(
    <>
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </>,
    size,
  )

export const ExternalLinkIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </>,
    size,
  )