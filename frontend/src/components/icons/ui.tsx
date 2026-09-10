/** UI icons. */

import type { FC } from 'react'
import { baseSvg, type IconProps } from './types'

export const SearchIcon: FC<IconProps> = ({ size = 20 }) =>
  baseSvg(
    <>
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </>,
    size,
  )

export const SettingsIcon: FC<IconProps> = ({ size = 20 }) =>
  baseSvg(
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </>,
    size,
  )

export const ChatIcon: FC<IconProps> = ({ size = 20 }) =>
  baseSvg(
    <>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </>,
    size,
  )

export const UserIcon: FC<IconProps> = ({ size = 20 }) =>
  baseSvg(
    <>
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </>,
    size,
  )

export const BotIcon: FC<IconProps> = ({ size = 20 }) =>
  baseSvg(
    <>
      <rect x="2" y="7" width="20" height="14" rx="2" />
      <circle cx="8" cy="14" r="1" />
      <circle cx="16" cy="14" r="1" />
      <path d="M12 3v4M8 3l2 2M16 3l-2 2" />
    </>,
    size,
  )

export const HelpIcon: FC<IconProps> = ({ size = 18 }) =>
  baseSvg(
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </>,
    size,
  )

export const InfoIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="16" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12.01" y2="8" />
    </>,
    size,
  )

export const AlertIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </>,
    size,
  )

export const GlobeIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <circle cx="12" cy="12" r="10" />
      <line x1="2" y1="12" x2="22" y2="12" />
      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
    </>,
    size,
  )

export const HashIcon: FC<IconProps> = ({ size = 14 }) =>
  baseSvg(
    <>
      <line x1="4" y1="9" x2="20" y2="9" />
      <line x1="4" y1="15" x2="20" y2="15" />
      <line x1="10" y1="3" x2="8" y2="21" />
      <line x1="16" y1="3" x2="14" y2="21" />
    </>,
    size,
  )

export const ClockIcon: FC<IconProps> = ({ size = 14 }) =>
  baseSvg(
    <>
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </>,
    size,
  )

export const NoteIcon: FC<IconProps> = ({ size = 14 }) =>
  baseSvg(
    <>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </>,
    size,
  )

export const CpuIcon: FC<IconProps> = ({ size = 18 }) =>
  baseSvg(
    <>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
      <line x1="9" y1="1" x2="9" y2="4" />
      <line x1="15" y1="1" x2="15" y2="4" />
      <line x1="9" y1="20" x2="9" y2="23" />
      <line x1="15" y1="20" x2="15" y2="23" />
      <line x1="20" y1="9" x2="23" y2="9" />
      <line x1="20" y1="14" x2="23" y2="14" />
      <line x1="1" y1="9" x2="4" y2="9" />
      <line x1="1" y1="14" x2="4" y2="14" />
    </>,
    size,
  )

export const QueueIcon: FC<IconProps> = ({ size = 18 }) =>
  baseSvg(
    <>
      <rect x="3" y="3" width="7" height="7" />
      <rect x="14" y="3" width="7" height="7" />
      <rect x="14" y="14" width="7" height="7" />
      <rect x="3" y="14" width="7" height="7" />
    </>,
    size,
  )

export const TableIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <rect x="4" y="5" width="4" height="3" rx="0.75" />
      <line x1="11" y1="6.5" x2="20" y2="6.5" />
      <rect x="4" y="10.5" width="4" height="3" rx="0.75" />
      <line x1="11" y1="12" x2="20" y2="12" />
      <rect x="4" y="16" width="4" height="3" rx="0.75" />
      <line x1="11" y1="17.5" x2="20" y2="17.5" />
    </>,
    size,
  )

export const GridIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <rect x="3" y="4" width="8" height="7" rx="1.25" />
      <rect x="13" y="4" width="8" height="7" rx="1.25" />
      <rect x="3" y="13" width="8" height="7" rx="1.25" />
      <rect x="13" y="13" width="8" height="7" rx="1.25" />
    </>,
    size,
  )

export const ChevronDownIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <polyline points="6 9 12 15 18 9" />
    </>,
    size,
  )

export const ChevronUpIcon: FC<IconProps> = ({ size = 16 }) =>
  baseSvg(
    <>
      <polyline points="6 15 12 9 18 15" />
    </>,
    size,
  )