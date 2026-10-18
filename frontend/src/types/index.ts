/**
 * Shared TypeScript types for the frontend.
 * Expand these as the backend API contracts land.
 */

export type AnalysisStatus = "idle" | "uploading" | "processing" | "ready" | "error";

export interface SkaterProfile {
  id: string;
  displayName: string;
}

export interface TechniqueAnalysis {
  id: string;
  status: AnalysisStatus;
  createdAt: string;
  summary?: string;
}
