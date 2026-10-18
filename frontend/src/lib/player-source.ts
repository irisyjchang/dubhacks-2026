import type { Analysis, MoveDetail, Pose } from "../types/api";

export type PlayerSource = { src: string; offset: number; pose?: Pose; move?: number };

/** Allow two pixels of even-dimension encoder rounding for 9:16 video. */
export function isPortraitCrop(width: number, height: number): boolean {
  return Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0
    && Math.abs(width - height * 9 / 16) <= 2;
}

export function cropSource(analysis: Analysis, detail?: MoveDetail): PlayerSource | null {
  if (analysis.player_view?.cropped && analysis.player_view.crop_video_url)
    return { src: analysis.player_view.crop_video_url, offset: 0, pose: analysis.player_view.pose };
  if (detail?.videos.crop)
    return { src: detail.videos.crop, offset: detail.move.segment.start_s, pose: detail.pose, move: detail.move.n };
  if (analysis.moves.length === 1 && analysis.single_move?.videos.crop)
    return { src: analysis.single_move.videos.crop, offset: Math.max(0, analysis.moves[0].segment.start_s - 0.5), move: analysis.moves[0].n };
  return null;
}
