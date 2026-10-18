"use client";
import { useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { useAnalysis } from "@/components/api/AnalysisProvider";

/** Open a history/deep-linked analysis on either the playback or results screen. */
export function useAnalysisRoute() {
  const { analysisId, openAnalysis } = useAnalysis();
  const queryId = useSearchParams().get("id");
  const loaded = useRef<string | null>(null);
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active || !queryId || queryId === loaded.current) return;
      loaded.current = queryId;
      if (analysisId !== queryId) openAnalysis(queryId);
    });
    return () => {
      active = false;
    };
  }, [queryId, analysisId, openAnalysis]);
}
