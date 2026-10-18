"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { skateApi, waitForAnalysis } from "@/lib/api";
import { useSessionMedia } from "@/components/media/SessionMedia";
import type {
  Analysis,
  HistoryVideo,
  Processing,
  ProgramType,
} from "@/types/api";

type Status = "idle" | "uploading" | "processing" | "ready" | "error";
type State = {
  analysis: Analysis | null;
  analysisId: string | null;
  status: Status;
  error: string | null;
  filename: string;
  startUpload: (file: File, program: ProgramType, track: boolean) => void;
  openAnalysis: (id: string, video?: HistoryVideo) => void;
  retry: () => void;
};
const Context = createContext<State | null>(null);
const storageKey = "skatecue.analysisId";
type RunOptions = { preserveFootage?: boolean; id?: string; fileName?: string };

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const { setRemote, associateAnalysis, videoRef } = useSessionMedia();
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [filename, setFilename] = useState("");
  const controller = useRef<AbortController | null>(null);
  const activeId = useRef<string | null>(null);
  const failed = useRef(false);
  const cache = useRef(new Map<string, Analysis>());
  const retryAction = useRef<() => void>(() => {});

  const run = useCallback(
    function run(
      first: (signal: AbortSignal) => Promise<Analysis | Processing>,
      options: RunOptions = {},
      uploading = false,
    ) {
      controller.current?.abort();
      failed.current = false;
      const task = new AbortController();
      controller.current = task;
      activeId.current = options.id || null;
      setAnalysis(null);
      setAnalysisId(options.id || null);
      setError(null);
      setStatus(uploading ? "uploading" : "processing");
      if (options.id) {
        try {
          localStorage.setItem(storageKey, options.id);
        } catch {
          /* Private browsing. */
        }
      }
      retryAction.current = () => run(first, options, uploading);
      void (async () => {
        try {
          const initial = await first(task.signal);
          if (task.signal.aborted) return;
          const id = initial.analysis_id;
          activeId.current = id;
          setAnalysisId(id);
          if (options.preserveFootage) associateAnalysis(id);
          try {
            localStorage.setItem(storageKey, id);
          } catch {
            /* Private browsing. */
          }
          retryAction.current = () =>
            run((signal) => skateApi.analysis(id, signal), { ...options, id });
          const result = await waitForAnalysis(initial, task.signal, () =>
            setStatus("processing"),
          );
          if (task.signal.aborted) return;
          if (result.status !== "done" || !Array.isArray(result.moves))
            throw new Error(
              "The API returned an incomplete analysis. Please retry.",
            );
          cache.current.set(id, result);
          if (cache.current.size > 5)
            cache.current.delete(cache.current.keys().next().value!);
          setAnalysis(result);
          // Results attach to the selected footage. Completing analysis must not reload its player.
          if (options.preserveFootage) {
            associateAnalysis(id);
            // Unsupported local codecs can use the API's H.264 conversion.
            if (videoRef.current?.error)
              setRemote(
                result.video_url,
                undefined,
                { analysisId: id, fileName: options.fileName },
                true,
              );
          } else setRemote(result.video_url, undefined, { analysisId: id });
          setStatus("ready");
        } catch (cause) {
          if (task.signal.aborted) return;
          failed.current = true;
          setError(
            cause instanceof Error
              ? cause.message
              : "The video could not be analyzed. Please retry.",
          );
          setStatus("error");
        }
      })();
    },
    [associateAnalysis, setRemote, videoRef],
  );

  const openAnalysis = useCallback(
    (id: string, video?: HistoryVideo) => {
      if (video?.video_url)
        setRemote(video.video_url, video.thumbnail_url || undefined, {
          analysisId: id,
          fileName: video.filename || undefined,
          uploadedAt: new Date(video.uploaded_at * 1000).toISOString(),
        });
      if (
        activeId.current === id &&
        !failed.current &&
        !controller.current?.signal.aborted
      )
        return;
      setFilename(video?.filename || "");
      const stored = cache.current.get(id);
      if (stored) {
        controller.current?.abort();
        activeId.current = id;
        setAnalysis(stored);
        setAnalysisId(id);
        setStatus("ready");
        setError(null);
        setRemote(stored.video_url, video?.thumbnail_url || undefined, {
          analysisId: id,
          fileName: video?.filename || undefined,
        });
        try {
          localStorage.setItem(storageKey, id);
        } catch {
          /* Private browsing. */
        }
        return;
      }
      run((signal) => skateApi.analysis(id, signal), { id });
    },
    [run, setRemote],
  );
  const startUpload = useCallback(
    (file: File, program: ProgramType, track: boolean) => {
      setFilename(file.name);
      try {
        localStorage.removeItem(storageKey);
      } catch {
        /* Private browsing. */
      }
      run(
        (signal) => skateApi.analyze(file, program, track, signal),
        { preserveFootage: true, fileName: file.name },
        true,
      );
    },
    [run],
  );
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active || new URLSearchParams(window.location.search).has("id"))
        return;
      let id: string | null = null;
      try {
        id = localStorage.getItem(storageKey);
      } catch {
        /* Private browsing. */
      }
      if (id) openAnalysis(id);
    });
    return () => {
      active = false;
      controller.current?.abort();
    };
  }, [openAnalysis]);
  return (
    <Context.Provider
      value={{
        analysis,
        analysisId,
        status,
        error,
        filename,
        startUpload,
        openAnalysis,
        retry: () => retryAction.current(),
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useAnalysis() {
  const value = useContext(Context);
  if (!value) throw new Error("useAnalysis requires AnalysisProvider");
  return value;
}
