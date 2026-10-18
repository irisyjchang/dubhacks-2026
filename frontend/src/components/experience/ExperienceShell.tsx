"use client";
import Link from "next/link";
import { APP_NAME } from "@/lib/constants";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { AuthControls, WelcomeGreeting } from "@/components/auth/AuthControls";
import { useSessionMedia } from "@/components/media/SessionMedia";
import { useAnalysis } from "@/components/api/AnalysisProvider";
import type { HistoryVideo, ProgramType } from "@/types/api";
import { PersistentStage } from "./PersistentStage";
import { Timeline } from "./Timeline";
import { Feedback } from "./Feedback";
import { Icon } from "./Icons";
import "./immersive.css";
const Experience = createContext<{
  chooseFootage: () => void;
  openFeedback: () => void;
  openClip: (id: string, video: HistoryVideo) => void;
} | null>(null);
export function useExperience() {
  const value = useContext(Experience);
  if (!value) throw new Error("ExperienceShell is required");
  return value;
}
export function ExperienceShell({
  children,
  authEnabled,
}: {
  children: ReactNode;
  authEnabled: boolean;
}) {
  const path = usePathname();
  const router = useRouter();
  const { media, setUpload, playback, setRate, presentation, croppedPresentation, showPresentation, showOriginal } =
    useSessionMedia();
  const { analysis, analysisId, status, error, filename, startUpload, openAnalysis, retry } = useAnalysis();
  const pendingAnalysis = useRef<string | true | null>(null);
  useEffect(() => {
    if (status === "ready" && pendingAnalysis.current &&
      (pendingAnalysis.current === true || pendingAnalysis.current === analysisId)) {
      pendingAnalysis.current = null;
      router.push("/analysis");
    }
  }, [status, analysisId, router]);
  const openClip = (id: string, video: HistoryVideo) => {
    if (analysisId === id && status === "ready") {
      router.push("/analysis");
      return;
    }
    pendingAnalysis.current = id;
    openAnalysis(id, video);
  };
  const input = useRef<HTMLInputElement>(null);
  const [pose, setPose] = useState(false);
  const [geometry, setGeometry] = useState(false);
  const [feedback, setFeedback] = useState(false);
  const [program, setProgram] = useState<ProgramType>("unk");
  const [track, setTrack] = useState(true);
  const [fileError, setFileError] = useState("");
  const isAnalysis = path === "/analysis" || path === "/plan";
  const isLibrary = path === "/library";
  const isAuth =
    path.startsWith("/sign-") || path === "/login" || path === "/signup";
  const hasVideo = Boolean(media.src);
  const hasPose = Boolean(
    playback.ready &&
      analysis?.analysis_id === media.analysisId,
  );
  const chooseFootage = () => input.current?.click();
  const style = {
    "--scene-rgb": `${media.tint.r}, ${media.tint.g}, ${media.tint.b}`,
  } as CSSProperties;
  return (
    <Experience.Provider
      value={{ chooseFootage, openClip, openFeedback: () => setFeedback(true) }}
    >
      <div
        className={`experience ${hasVideo ? "has-footage" : "is-empty"} ${isAnalysis ? "is-analysis" : ""} ${isLibrary ? "is-library" : ""} ${isAuth ? "is-auth" : ""} ${feedback && isAnalysis ? "feedback-open" : ""}`}
        style={style}
      >
        <PersistentStage
          pose={isAnalysis && pose}
          geometry={isAnalysis && geometry}
        />
        <header className="app-header">
          <Link href="/" className="wordmark" aria-label={`${APP_NAME} Home`}>
            {APP_NAME}
          </Link>
          <div className="account-actions">
            {path === "/" && (
              <span className="home-greeting"><WelcomeGreeting enabled={authEnabled} /></span>
            )}
            {hasVideo && !isAuth && (
              <button
                type="button"
                className="icon-button"
                aria-label="Replace video"
                title="Replace video"
                onClick={chooseFootage}
              >
                <Icon name="change" />
              </button>
            )}
            <AuthControls enabled={authEnabled} />
          </div>
        </header>
        <input
          ref={input}
          type="file"
          className="sr-only"
          aria-label="Choose video footage"
          accept="video/*,.mp4,.mov,.m4v,.avi,.mkv,.webm"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (!file) return;
            if (
              !file.type.startsWith("video/") &&
              !/\.(mp4|mov|m4v|avi|mkv|webm)$/i.test(file.name)
            ) {
              setFileError("Choose a video from your library.");
              return;
            }
            setFileError("");
            setPose(false);
            setGeometry(false);
            setFeedback(false);
            setUpload(file);
            pendingAnalysis.current = true;
            startUpload(file, program, track);
          }}
        />
        <main className="route-content">{children}</main>
        {!isAuth && hasVideo && !isLibrary && (
          <div className="footage-caption">
            <div className="video-view-toggle" role="group" aria-label="Video framing">
              <button type="button" aria-pressed={!presentation} onClick={showOriginal}>Full video</button>
              <button type="button" aria-pressed={presentation?.kind === "crop"}
                disabled={!croppedPresentation}
                title={croppedPresentation ? "Show the skater crop" : "Cropped video becomes available after analysis"}
                onClick={() => { if (croppedPresentation) showPresentation(croppedPresentation); }}>Cropped</button>
            </div>
          </div>
        )}
        {!isAuth && (status === "uploading" || status === "processing") && (
          <div className="processing-overlay">
            <div className="processing-card" role="status" aria-live="polite" aria-atomic="true">
              <span className="processing-ring" aria-hidden="true" />
              <h2>{status === "uploading" ? "Uploading your video" : "Your video is processing"}</h2>
              {filename && <p className="processing-filename">{filename}</p>}
              <p>Analysis will open automatically when it’s ready.</p>
            </div>
          </div>
        )}
        {!isAuth && (
          <div className="stage-notice" aria-live="polite">
            {fileError || playback.error ? (
              <p role="alert">{fileError || playback.error}</p>
            ) : error ? (
              <p role="alert">
                Analysis couldn’t finish.{" "}
                <button type="button" className="text-action" onClick={retry}>
                  Retry
                </button>{" "}
                <button
                  type="button"
                  className="text-action"
                  onClick={() => {
                    setFeedback(true);
                    router.push("/analysis");
                  }}
                >
                  Details
                </button>
              </p>
            ) : null}
          </div>
        )}
        {isAnalysis && (
          <div className="analysis-tools" aria-label="Analysis tools">
            <button
              type="button"
              className="tool-button"
              aria-label="Pose tracking"
              aria-pressed={pose}
              disabled={!hasPose}
              title={
                hasPose
                  ? "Pose tracking"
                  : "Pose tracking becomes available when analysis finishes"
              }
              onClick={() => setPose((value) => !value)}
            >
              <Icon name="pose" />
              <span>Pose</span>
            </button>
            <button
              type="button"
              className="tool-button"
              aria-label="Geometry"
              aria-pressed={geometry}
              disabled={!hasPose}
              title={
                hasPose
                  ? "Joint angles"
                  : "Joint angles require pose tracking data"
              }
              onClick={() => setGeometry((value) => !value)}
            >
              <Icon name="geometry" />
              <span>Angles</span>
            </button>
            <button
              type="button"
              className="tool-button"
              aria-label="AI feedback"
              aria-expanded={feedback}
              onClick={() => setFeedback((value) => !value)}
            >
              <Icon name="feedback" />
              <span>Feedback</span>
            </button>
            <button
              type="button"
              className="tool-button speed-tool"
              aria-label={`Playback speed ${playback.rate}x`}
              title="Playback speed"
              disabled={!hasVideo}
              onClick={() => {
                const rates = [0.25, 0.5, 0.75, 1, 1.5, 2];
                setRate(
                  rates[(rates.indexOf(playback.rate) + 1) % rates.length],
                );
              }}
            >
              <span className="speed-number">{playback.rate}×</span>
              <span>Speed</span>
            </button>
          </div>
        )}
        <div hidden={!isAnalysis || !feedback}>
          <Feedback
            onClose={() => setFeedback(false)}
            program={program}
            setProgram={setProgram}
            track={track}
            setTrack={setTrack}
          />
        </div>
        <div
          className="persistent-controls"
          hidden={isAuth || isLibrary || !hasVideo}
        >
          <Timeline detailed={isAnalysis || status === "ready"} />
        </div>
        {!isAuth && (
          <nav className="main-nav" aria-label="Main navigation">
            {[
              { href: "/", label: "Home" },
              { href: "/analysis", label: "Analysis" },
              { href: "/library", label: "Library" },
            ].map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                onClick={() => { pendingAnalysis.current = null; }}
                aria-current={
                  (href === "/analysis" ? isAnalysis : path === href)
                    ? "page"
                    : undefined
                }
              >
                {label}
              </Link>
            ))}
          </nav>
        )}
      </div>
    </Experience.Provider>
  );
}
