// Feature: draggable-card-layout
// Utility types and pure functions for the draggable card layout system.

export type CardId = 'preview' | 'task' | 'chat' | 'toolbar'

export interface CardState {
  x: number      // left (px)
  y: number      // top (px)
  width: number  // px
  height: number // px
}

export interface LayoutData {
  cards: Record<CardId, CardState>
  logDetached: boolean
}

const MARGIN = 40

/**
 * Clamp a card position so that at least MARGIN (40px) of the card
 * remains visible inside the viewport.
 *
 * Rules:
 *   x >= -(w - 40)   (left edge can go off-screen but 40px must stay visible)
 *   y >= 0           (top edge must not go above viewport)
 *   x <= vw - 40     (right side: at least 40px must stay visible)
 *   y <= vh - 40     (bottom side: at least 40px must stay visible)
 */
export function clamp(
  x: number,
  y: number,
  w: number,
  h: number,
  vw: number,
  vh: number,
): { x: number; y: number } {
  return {
    x: Math.min(Math.max(x, -(w - MARGIN)), vw - MARGIN),
    y: Math.min(Math.max(y, 0), vh - MARGIN),
  }
}

/**
 * Compute the default card layout proportional to the given viewport size.
 *
 * - preview : width = vw * 0.58, height = width * 9/16, position (10, 10)
 * - task    : x = previewW + 20, y = 10, width = vw - x - 10, height = 180
 * - chat    : x = task.x, y = task.y + task.height + 10, width = task.width,
 *             height = vh - y - 80
 * - toolbar : x = task.x, y = vh - 60, width = task.width, height = 52
 */
export function computeDefaultLayout(vw: number, vh: number): Record<CardId, CardState> {
  const previewW = Math.round(vw * 0.58)
  const previewH = Math.round((previewW * 9) / 16)

  const taskX = previewW + 20
  const taskY = 10
  const taskW = vw - taskX - 10
  const taskH = 170  // actions(~90) + progress bar(~50) + status text(~30)

  const chatX = taskX
  const chatY = taskY + taskH + 10
  const chatW = taskW
  const chatH = vh - chatY - 60  // leave room for toolbar

  const toolbarX = taskX
  const toolbarY = vh - 44
  const toolbarW = taskW
  const toolbarH = 44

  return {
    preview: { x: 10, y: 10, width: previewW, height: previewH },
    task:    { x: taskX, y: taskY, width: taskW, height: taskH },
    chat:    { x: chatX, y: chatY, width: chatW, height: chatH },
    toolbar: { x: toolbarX, y: toolbarY, width: toolbarW, height: toolbarH },
  }
}

/**
 * Parse a raw localStorage string into a LayoutData object.
 * Returns null if the string is missing, malformed, or structurally invalid.
 */
export function parseStoredLayout(raw: string | null | undefined): LayoutData | null {
  if (!raw) return null

  try {
    const parsed = JSON.parse(raw) as unknown

    if (typeof parsed !== 'object' || parsed === null) return null

    const obj = parsed as Record<string, unknown>

    if (typeof obj.logDetached !== 'boolean') return null
    if (typeof obj.cards !== 'object' || obj.cards === null) return null

    const cards = obj.cards as Record<string, unknown>
    const cardIds: CardId[] = ['preview', 'task', 'chat', 'toolbar']

    for (const id of cardIds) {
      const card = cards[id]
      if (typeof card !== 'object' || card === null) return null
      const c = card as Record<string, unknown>
      if (
        typeof c.x !== 'number' ||
        typeof c.y !== 'number' ||
        typeof c.width !== 'number' ||
        typeof c.height !== 'number'
      ) {
        return null
      }
    }

    return {
      cards: obj.cards as Record<CardId, CardState>,
      logDetached: obj.logDetached as boolean,
    }
  } catch {
    return null
  }
}
