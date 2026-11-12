/** Brand icons. */

import type { FC } from 'react'
import type { IconProps } from './types'

export const MoleculeLogo: FC<IconProps> = ({ size = 72 }) => (
  <svg width={size} height={size} viewBox="0 0 72 72" fill="none">
    <defs>
      <linearGradient id="mblogo-bg" x1="0" y1="0" x2="72" y2="72" gradientUnits="userSpaceOnUse">
        <stop offset="0" stopColor="#100F0F" />
        <stop offset="1" stopColor="#1C1B1A" />
      </linearGradient>
    </defs>
    <rect width="72" height="72" rx="16" fill="url(#mblogo-bg)" />
    <polygon points="36,24 46.4,30 46.4,42 36,48 25.6,42 25.6,30" stroke="#878580" strokeWidth={2} strokeLinejoin="round" opacity={0.75} />
    <polygon points="36,16 42.9,20 42.9,28 36,32 29.1,28 29.1,20" stroke="#3AA99F" strokeWidth={2.5} strokeLinejoin="round" />
    <polygon points="46.4,34 53.3,38 53.3,46 46.4,50 39.5,46 39.5,38" stroke="#8B7EC8" strokeWidth={2.5} strokeLinejoin="round" />
    <polygon points="25.6,34 32.5,38 32.5,46 25.6,50 18.7,46 18.7,38" stroke="#66A0C8" strokeWidth={2.5} strokeLinejoin="round" />
  </svg>
)