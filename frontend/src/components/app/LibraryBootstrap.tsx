/** Bootstrap screen shown when no library root is configured.
 *
 *  Renders the Welcome screen (library configuration) plus the global
 *  ToastContainer.
 */

import Welcome from '../Welcome'
import { ToastContainer } from '../ui'

export function LibraryBootstrap() {
  return (
    <div className="app-shell app-shell--no-library">
      <main className="app-shell__main">
        <Welcome />
      </main>
      <ToastContainer />
    </div>
  )
}
