import { isClerkConfigured } from "@/lib/auth-config";
import { clerkMiddleware } from "@clerk/nextjs/server";

import {
  NextResponse,
  type NextRequest,
  type NextFetchEvent,
} from "next/server";

const authMiddleware = clerkMiddleware();
export default function proxy(request: NextRequest, event: NextFetchEvent) {
  if (!isClerkConfigured()) return NextResponse.next();
  return authMiddleware(request, event);
}

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/(.*)",
  ],
};
