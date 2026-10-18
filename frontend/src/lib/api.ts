import type {
  Analysis,
  HistoryVideo,
  MoveDetail,
  MoveView,
  Processing,
  ProgramType,
} from "../types/api";

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function apiUrl(path: string) {
  const base = process.env.NEXT_PUBLIC_SKATE_API_URL?.trim().replace(
    /\/+$/,
    "",
  );
  if (!base)
    throw new ApiError(
      "Set NEXT_PUBLIC_SKATE_API_URL in .env.local to connect your skating API.",
      0,
    );
  return `${base}${path}`;
}

export function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason);
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

async function request<T>(
  path: string,
  signal: AbortSignal,
  body?: FormData,
): Promise<T> {
  const url = apiUrl(path);
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await fetch(url, {
        method: body ? "POST" : "GET",
        body,
        cache: "no-store",
        signal: AbortSignal.any([signal, AbortSignal.timeout(95_000)]),
      });
      // Tunnel errors often return HTML. Preserve the HTTP status for retry/error handling.
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = data?.error || data?.detail;
        throw new ApiError(
          typeof detail === "string"
            ? detail
            : `The skating API returned ${response.status}. Please try again.`,
          response.status,
        );
      }
      if (!data)
        throw new ApiError("The API returned an unreadable response.", 502);
      if (response.status === 202) {
        data.retry_after_s = Math.max(
          1,
          Number(data.retry_after_s || response.headers.get("Retry-After")) ||
            15,
        );
      }
      return data as T;
    } catch (error) {
      if (signal.aborted) throw error;
      if (error instanceof ApiError && error.status < 500) throw error;
      if (attempt === 0) {
        await delay(1000, signal);
        continue;
      }
      if (error instanceof ApiError) throw error;
      throw new ApiError(
        "Could not reach the skating API. Check your connection and that the API tunnel is still running, then retry.",
        0,
      );
    }
  }
  throw new ApiError("Could not reach the skating API.", 0);
}

export const skateApi = {
  history: (signal: AbortSignal) =>
    request<{ videos: HistoryVideo[] }>("/app/history", signal),
  analysis: (id: string, signal: AbortSignal) =>
    request<Analysis | Processing>(
      `/app/analysis/${encodeURIComponent(id)}`,
      signal,
    ),
  analyze: (
    file: File,
    program: ProgramType,
    track: boolean,
    signal: AbortSignal,
  ) => {
    const body = new FormData();
    body.append("video", file);
    body.append("program_type", program);
    body.append("perceptron_track", String(track));
    return request<Analysis | Processing>("/app/analyze", signal, body);
  },
  move: (id: string, n: number, view: MoveView, signal: AbortSignal) =>
    request<MoveDetail>(
      `/app/moves/${encodeURIComponent(id)}/${n}?view=${view}`,
      signal,
    ),
};

/** Resume a job with the server's polling interval; the caller owns cancellation. */
export async function waitForAnalysis(
  result: Analysis | Processing,
  signal: AbortSignal,
  onProcessing: () => void = () => {},
): Promise<Analysis> {
  while (result.status === "processing") {
    onProcessing();
    await delay((result.retry_after_s || 15) * 1000, signal);
    result = await skateApi.analysis(result.analysis_id, signal);
  }
  return result;
}
