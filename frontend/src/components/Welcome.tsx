import { useState } from 'react'
import { motion } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import { FolderIcon, MoleculeLogo } from './icons'
import { StaggerContainer, StaggerItem } from './animations/StaggerContainer'
import { showToast } from '@/hooks/useToast'
import { fadeIn, logoEntrance } from '@/hooks/useAnimations'
import Button from '@/components/ui/Button'
import PageTitle from '@/components/ui/PageTitle'
import BodyText from '@/components/ui/BodyText'
import { configureLibrary } from '@/api/http/library'
import { useAppContext } from '@/context/AppContext'
import { getUserFacingError } from '@/utils/errors'

export default function Welcome() {
  const { t } = useTranslation()
  const { setLibraryRoot } = useAppContext()
  const [dir, setDir] = useState('')
  const [loading, setLoading] = useState(false)

  const handleConfigure = async () => {
    if (!dir.trim()) return
    setLoading(true)
    try {
      const resp = await configureLibrary(dir.trim())
      if (resp.success && resp.root) {
        setLibraryRoot(resp.root)
      } else {
        showToast(resp.error || t('welcome.configureFailed'), 'error')
      }
    } catch (e) {
      showToast(
        t('welcome.configureError', {
          error: getUserFacingError(e),
        }),
        'error'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <motion.div
      variants={fadeIn}
      initial="hidden"
      animate="visible"
      className="welcome-home"
    >
      <div className="welcome-home-inner">
        <StaggerContainer stagger={0.08}>
          <StaggerItem>
            <motion.div
              variants={logoEntrance}
              initial="hidden"
              animate="visible"
              className="welcome-logo"
            >
              <MoleculeLogo size={72} />
            </motion.div>
          </StaggerItem>

          <StaggerItem>
            <PageTitle className="welcome-title">MBForge</PageTitle>
          </StaggerItem>

          <StaggerItem>
            <BodyText size="lg" className="welcome-subtitle">
              {t('library.configureLibrary')}
            </BodyText>
          </StaggerItem>

          <StaggerItem>
            <BodyText className="welcome-description">
              {t('library.configureDescription')}
            </BodyText>
          </StaggerItem>

          <StaggerItem>
            <div className="welcome-config-form">
              <div className="welcome-dir-input-wrapper">
                <input
                  type="text"
                  className="welcome-dir-input"
                  placeholder={t('library.libraryRoot')}
                  value={dir}
                  onChange={(e) => setDir(e.target.value)}
                />
              </div>
              <Button
                variant="primary"
                size="lg"
                onClick={handleConfigure}
                disabled={!dir.trim() || loading}
                icon={<FolderIcon size={16} />}
              >
                {t('library.createLibrary')}
              </Button>
            </div>
          </StaggerItem>
        </StaggerContainer>
      </div>
    </motion.div>
  )
}
