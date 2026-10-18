import type { CSSProperties } from "react";
export function Icon({ name, style }: { name: string; style?: CSSProperties }) {
  const paths: Record<string, React.ReactNode> = {
    replay: <path d="M20 7a8 8 0 1 0 1 8M20 3v5h-5" />,
    back: <path d="m12 5-7 7 7 7M5 12h15" />,
    add: <path d="M12 4v16M4 12h16" />,
    change: (
      <>
        <path d="M4 8h14m-4-4 4 4-4 4M20 16H6m4-4-4 4 4 4" />
      </>
    ),
    play: <path d="m9 5 11 7-11 7Z" />,
    pause: (
      <>
        <path d="M8 5v14M16 5v14" />
      </>
    ),
    prev: (
      <>
        <path d="M5 5v14m14-14L8 12l11 7Z" />
      </>
    ),
    next: (
      <>
        <path d="M19 5v14M5 5l11 7-11 7Z" />
      </>
    ),
    pose: (
      <>
        <circle cx="12" cy="4" r="2" />
        <path d="M12 6v7m-7-4 7 1 7-1m-7 4-5 8m5-8 5 8" />
      </>
    ),
    geometry: (
      <>
        <path d="m12 3 10 18H2Z" />
        <path d="M7 21v-6h6" />
      </>
    ),
    feedback: (
      <>
        <path d="m12 2 2.4 6.7L21 11l-6.6 2.3L12 20l-2.4-6.7L3 11l6.6-2.3Z" />
        <path d="m20 2 1 3 3 1" />
      </>
    ),
    close: <path d="m6 6 12 12M6 18 18 6" />,
    muted: (
      <>
        <path d="M10 4 5 8H2v8h3l5 4ZM16 9l6 6m0-6-6 6" />
      </>
    ),
    sound: (
      <>
        <path d="M10 4 5 8H2v8h3l5 4ZM15 8c3 2 3 6 0 8m4-12c5 4 5 12 0 16" />
      </>
    ),
    expand: <path d="M9 3H3v6m12-6h6v6M3 15v6h6m12-6v6h-6" />,
  };
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.25"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
    >
      {paths[name] || paths.add}
    </svg>
  );
}
