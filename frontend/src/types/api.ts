export type ProgramType = "sp" | "fs" | "unk";
export type MoveView = "normal" | "skeleton" | "skeleton_only";
export interface Pose {
  fps: number;
  width: number;
  height: number;
  duration_s?: number;
  min_confidence: number;
  edges: [number, number][];
  frames: { t: number; kp: [number, number, number][] }[];
  skater_boxes?: { t: number; box: [number, number, number, number] }[];
}
export interface Move {
  n: number;
  name: string;
  code: string;
  kind: string;
  segment: { start_s: number; end_s: number };
  score: number;
  points_lost: number;
  fall: boolean;
  went_right: string;
  went_wrong: string;
  video_url: string;
}
export interface Coaching {
  summary: string;
  went_right: string[];
  went_wrong: { issue: string; rule: string }[];
  improvements: { fix: string; drill: string; cue: string }[];
}
export interface MoveVideos {
  segment: string;
  crop?: string;
  skeleton?: string;
}
export interface MoveDetail {
  analysis_id: string;
  move: Omit<Move, "went_right" | "went_wrong" | "video_url"> & {
    start_s: number;
    end_s: number;
    bv: number;
    goe: number;
    det_score: number;
    physics?: { air_time_s?: number; height_m?: number; revolutions?: number };
  };
  detail: Coaching;
  videos: MoveVideos;
  pose?: Pose;
}
export interface Analysis {
  analysis_id: string;
  status: "done";
  score: number;
  tes: number;
  duration_s: number;
  total_points_lost: number;
  summary: { went_right: string; could_improve: string };
  moves: Move[];
  video_url: string;
  player_view?: PlayerView;
  default_move?: MoveDetail;
  pose?: Pose;
  coach?: { model: string };
  person_tracking?: { status: string; warning?: string | null };
  single_move?: { detail: Coaching; videos: MoveVideos };
}
export interface PlayerView {
  analysis_id: string;
  video_url: string;
  cropped: boolean;
  crop_video_url?: string | null;
  pose?: Pose;
  timeline: (Move & { jump_to_s: number })[];
}
export interface Processing {
  analysis_id: string;
  status: "processing";
  retry_after_s?: number;
}
export interface HistoryVideo {
  analysis_id: string;
  status: "processing" | "done" | "failed";
  uploaded_at: number;
  filename: string | null;
  score: number | null;
  duration_s: number | null;
  moves: number | null;
  thumbnail_url: string | null;
  preview_url: string | null;
  video_url: string | null;
}
