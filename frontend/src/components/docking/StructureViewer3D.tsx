import { useEffect, useRef } from 'react'
import * as $3Dmol from '3dmol'

export interface DockingBox3D {
  center: number[]
  size: number[]
}

interface Props {
  /** URL of the receptor PDB (protein), or null when none is selected. */
  receptorUrl: string | null
  /** URL of the ligand pose SDF to overlay, or null. */
  poseUrl: string | null
  /** Search box to draw as a wireframe, or null. */
  box: DockingBox3D | null
  backgroundColor?: string
  ariaLabel?: string
}

/**
 * Protein + ligand + docking-box renderer (3Dmol.js).
 *
 * 3Dmol owns a WebGL canvas imperatively, so the viewer is created once and the
 * scene is rebuilt whenever the inputs change. Models are fetched lazily as
 * text (PDB / SDF) so the backend only needs to serve raw files.
 */
export default function StructureViewer3D({
  receptorUrl,
  poseUrl,
  box,
  backgroundColor = '#000000',
  ariaLabel = '3D structure',
}: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const viewerRef = useRef<$3Dmol.GLViewer | null>(null)

  // Create the viewer once for the host element.
  useEffect(() => {
    if (!hostRef.current || viewerRef.current) return
    viewerRef.current = $3Dmol.createViewer(hostRef.current, { backgroundColor })
    return () => {
      viewerRef.current?.clear()
      viewerRef.current = null
    }
  }, [backgroundColor])

  // Rebuild the scene when inputs change.
  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer) return
    let cancelled = false

    const run = async () => {
      viewer.removeAllModels()
      viewer.removeAllShapes()
      let added = false

      if (receptorUrl) {
        const text = await (await fetch(receptorUrl)).text()
        if (cancelled) return
        const protein = viewer.addModel(text, 'pdb')
        viewer.setStyle({ model: protein.getID() }, { cartoon: { color: 'spectrum' } })
        added = true
      }

      if (poseUrl) {
        const sdf = await (await fetch(poseUrl)).text()
        if (cancelled) return
        const ligand = viewer.addModel(sdf, 'sdf')
        viewer.setStyle(
          { model: ligand.getID() },
          { stick: { radius: 0.15 }, sphere: { scale: 0.25 } },
        )
        added = true
      }

      if (box && box.center.length === 3 && box.size.length === 3) {
        viewer.addBox({
          center: { x: box.center[0], y: box.center[1], z: box.center[2] },
          dimensions: { w: box.size[0], h: box.size[1], d: box.size[2] },
          color: '#6366f1',
          alpha: 0.12,
          wireframe: true,
        })
      }

      if (added) {
        viewer.zoomTo()
      }
      viewer.render()
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [receptorUrl, poseUrl, box])

  return <div ref={hostRef} className="docking-viewer3d" role="img" aria-label={ariaLabel} />
}
