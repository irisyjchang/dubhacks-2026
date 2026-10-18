"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

export type MediaTone = "light" | "dark";
export type SessionMedia = {
  src: string;
  kind: "image" | "video";
  fileName?: string;
  uploadedAt?: string;
  analysisId?: string;
  poster: string;
  tone: MediaTone;
  accent: string;
  tint: { r: number; g: number; b: number };
};
import type { Pose } from "@/types/api";

export type VideoPresentation = {
  pose?: Pose;
  move?: number;
  src: string;
  offset: number;
  label: string;
  kind: "segment" | "crop" | "skeleton" | "skeleton_only";
};
export type Playback = {
  time: number;
  duration: number;
  playing: boolean;
  ready: boolean;
  rate: number;
  muted: boolean;
  error: string | null;
};
type RemoteMetadata = {
  analysisId?: string;
  fileName?: string;
  uploadedAt?: string;
};
type MediaContext = {
  media: SessionMedia;
  uploadFile: File | null;
  videoRef: RefObject<HTMLVideoElement | null>;
  pendingPlaybackRef: RefObject<{ time: number; play: boolean } | null>;
  presentation: VideoPresentation | null;
  croppedPresentation: VideoPresentation | null;
  playback: Playback;
  setUpload: (file: File) => void;
  setRemote: (
    src: string,
    poster?: string,
    metadata?: RemoteMetadata,
    force?: boolean,
  ) => void;
  associateAnalysis: (id: string) => void;
  updateLook: (
    look: Pick<SessionMedia, "accent" | "tint"> & { poster?: string },
  ) => void;
  updatePlayback: (value: Partial<Playback>) => void;
  togglePlay: () => void;
  seek: (time: number, pause?: boolean) => void;
  setRate: (rate: number) => void;
  toggleMuted: () => void;
  showPresentation: (presentation: VideoPresentation, position?: { time: number; play: boolean }) => void;
  showOriginal: () => void;
};
const EMPTY: SessionMedia = {
  src: "",
  kind: "image",
  poster: "",
  tone: "light",
  accent: "rgb(226, 230, 232)",
  tint: { r: 226, g: 230, b: 232 },
};
const INITIAL_PLAYBACK: Playback = {
  time: 0,
  duration: 0,
  playing: false,
  ready: false,
  rate: 1,
  muted: true,
  error: null,
};
const Context = createContext<MediaContext | null>(null);

export function SessionMediaProvider({ children }: { children: ReactNode }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pendingPlaybackRef = useRef<{ time: number; play: boolean } | null>(
    null,
  );
  const snapshot = useRef(EMPTY);
  const objectUrl = useRef<string | null>(null);
  const presentationRef = useRef<VideoPresentation | null>(null);
  const [media, setMedia] = useState(EMPTY);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [presentation, setPresentation] = useState<VideoPresentation | null>(
    null,
  );
  const [playback, setPlayback] = useState(INITIAL_PLAYBACK);
  const [croppedPresentation, setCroppedPresentation] = useState<VideoPresentation | null>(null);
  const commit = useCallback((next: SessionMedia) => {
    snapshot.current = next;
    setMedia(next);
  }, []);
  const resetPresentation = useCallback(() => {
    presentationRef.current = null;
    setPresentation(null);
  }, []);
  const releaseUpload = useCallback(() => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = null;
  }, []);

  const setUpload = useCallback(
    (file: File) => {
      releaseUpload();
      const src = URL.createObjectURL(file);
      objectUrl.current = src;
      pendingPlaybackRef.current = { time: 0, play: true };
      resetPresentation();
      setCroppedPresentation(null);
      setUploadFile(file);
      setPlayback({
        ...INITIAL_PLAYBACK,
        muted: videoRef.current?.muted ?? true,
      });
      commit({
        ...snapshot.current,
        src,
        kind: "video",
        fileName: file.name,
        uploadedAt: new Date().toISOString(),
        analysisId: undefined,
        poster: "",
        tone: "dark",
      });
    },
    [commit, releaseUpload, resetPresentation],
  );

  const setRemote = useCallback(
    (
      src: string,
      poster = "",
      metadata: RemoteMetadata = {},
      force = false,
    ) => {
      const current = snapshot.current;
      const knownMetadata = Object.fromEntries(
        Object.entries(metadata).filter(([, value]) => value !== undefined),
      );
      // Opening the same analysis never replaces a still-playing local upload or reloads its URL.
      if (
        !force &&
        (current.src === src ||
          (metadata.analysisId &&
            metadata.analysisId === current.analysisId &&
            current.src))
      ) {
        commit({
          ...current,
          ...knownMetadata,
          poster: poster || current.poster,
        });
        return;
      }
      const previous = videoRef.current;
      const preservePlayback = Boolean(force && current.analysisId === metadata.analysisId && previous);
      const resume = preservePlayback && previous
        ? { time: previous.currentTime, play: !previous.paused }
        : { time: 0, play: true };
      releaseUpload();
      setUploadFile(null);
      resetPresentation();
      setCroppedPresentation(null);
      pendingPlaybackRef.current = resume;
      setPlayback({
        ...INITIAL_PLAYBACK,
        rate: preservePlayback ? previous?.playbackRate ?? 1 : 1,
        muted: videoRef.current?.muted ?? true,
      });
      commit({
        ...current,
        ...metadata,
        fileName: metadata.fileName ?? current.fileName,
        uploadedAt: metadata.uploadedAt ?? current.uploadedAt,
        analysisId: metadata.analysisId,
        src,
        kind: "video",
        poster,
        tone: "dark",
      });
    },
    [commit, releaseUpload, resetPresentation],
  );

  const associateAnalysis = useCallback(
    (id: string) => {
      commit({ ...snapshot.current, analysisId: id });
    },
    [commit],
  );
  const updateLook = useCallback(
    (look: Pick<SessionMedia, "accent" | "tint"> & { poster?: string }) => {
      commit({ ...snapshot.current, ...look });
    },
    [commit],
  );
  const updatePlayback = useCallback(
    (value: Partial<Playback>) =>
      setPlayback((current) => ({ ...current, ...value })),
    [],
  );
  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video || !snapshot.current.src) return;
    if (video.paused)
      void video.play().catch(() =>
        updatePlayback({
          error: "Playback could not start. Tap play to try again.",
        }),
      );
    else video.pause();
  }, [updatePlayback]);
  const seek = useCallback(
    (time: number, pause = false) => {
      const video = videoRef.current;
      if (!video || !Number.isFinite(video.duration)) return;
      if (pause) video.pause();
      video.currentTime = Math.max(0, Math.min(video.duration, time));
      updatePlayback({ time: video.currentTime });
    },
    [updatePlayback],
  );
  const setRate = useCallback(
    (rate: number) => {
      if (videoRef.current) videoRef.current.playbackRate = rate;
      updatePlayback({ rate });
    },
    [updatePlayback],
  );
  const toggleMuted = useCallback(() => {
    const video = videoRef.current;
    if (video) {
      video.muted = !video.muted;
      updatePlayback({ muted: video.muted });
    }
  }, [updatePlayback]);
  const showPresentation = useCallback((next: VideoPresentation, position?: { time: number; play: boolean }) => {
    const video = videoRef.current;
    if (next.kind === "crop") setCroppedPresentation(next);
    if (presentationRef.current?.src === next.src) {
      if (position && video) { video.currentTime = position.time; if (!position.play) video.pause(); }
      presentationRef.current = next;
      setPresentation(next);
      return;
    }
    pendingPlaybackRef.current = position ?? {
      time: Math.max(
        0,
        (video?.currentTime || 0) +
          (presentationRef.current?.offset || 0) -
          next.offset,
      ),
      play: video ? !video.paused : true,
    };
    presentationRef.current = next;
    setPresentation(next);
  }, []);
  const showOriginal = useCallback(() => {
    if (!presentationRef.current) return;
    const video = videoRef.current;
    pendingPlaybackRef.current = {
      time: (video?.currentTime || 0) + presentationRef.current.offset,
      play: video ? !video.paused : true,
    };
    resetPresentation();
  }, [resetPresentation]);

  useEffect(
    () => () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    },
    [],
  );

  const value = useMemo(
    () => ({
      media,
      uploadFile,
      videoRef,
      pendingPlaybackRef,
      presentation,
      croppedPresentation,
      playback,
      setUpload,
      setRemote,
      associateAnalysis,
      updateLook,
      updatePlayback,
      togglePlay,
      seek,
      setRate,
      toggleMuted,
      showPresentation,
      showOriginal,
    }),
    [
      media,
      uploadFile,
      presentation,
      croppedPresentation,
      playback,
      setUpload,
      setRemote,
      associateAnalysis,
      updateLook,
      updatePlayback,
      togglePlay,
      seek,
      setRate,
      toggleMuted,
      showPresentation,
      showOriginal,
    ],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useSessionMedia() {
  const value = useContext(Context);
  if (!value) throw new Error("useSessionMedia requires SessionMediaProvider");
  return value;
}
