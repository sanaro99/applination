import type { TourSide } from "@/components/tour/tour-steps";

/** Gap (px) between the card and the spotlighted element. */
export const CARD_GAP = 16;
/** Minimum clearance (px) kept between the card and the viewport edge. */
export const VIEWPORT_MARGIN = 16;
/** Padding (px) added around the target when drawing the spotlight cutout. */
export const SPOTLIGHT_PADDING = 10;

/** A plain, serializable stand-in for DOMRect — the fields we actually use. */
export interface Rect {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
}

export interface CardPlacement {
  top: number;
  left: number;
}

/**
 * Where the card should sit for a given target + side, clamped to the
 * viewport so it can never render off-screen regardless of where the target is.
 */
export function computeCardPosition(
  target: Rect,
  side: TourSide,
  cardWidth: number,
  cardHeight: number,
  viewportWidth: number,
  viewportHeight: number,
): CardPlacement {
  let top: number;
  let left: number;

  switch (side) {
    case "top":
      top = target.top - CARD_GAP - cardHeight;
      left = target.left + target.width / 2 - cardWidth / 2;
      break;
    case "left":
      top = target.top + target.height / 2 - cardHeight / 2;
      left = target.left - CARD_GAP - cardWidth;
      break;
    case "right":
      top = target.top + target.height / 2 - cardHeight / 2;
      left = target.right + CARD_GAP;
      break;
    case "bottom":
    default:
      top = target.bottom + CARD_GAP;
      left = target.left + target.width / 2 - cardWidth / 2;
      break;
  }

  return {
    top: clamp(top, VIEWPORT_MARGIN, viewportHeight - cardHeight - VIEWPORT_MARGIN),
    left: clamp(left, VIEWPORT_MARGIN, viewportWidth - cardWidth - VIEWPORT_MARGIN),
  };
}

function clamp(value: number, min: number, max: number): number {
  if (max < min) return min;
  return Math.min(Math.max(value, min), max);
}
