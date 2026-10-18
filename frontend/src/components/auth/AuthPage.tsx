import Link from "next/link";
import { APP_NAME } from "@/lib/constants";
import type { ReactNode } from "react";

export function AuthPage({ children }: { children: ReactNode }) {
  return (
    <main className="relative flex min-h-dvh flex-col items-center justify-center gap-6 px-4 py-12">
      <Link href="/" className="font-serif text-4xl text-white">
        {APP_NAME}
      </Link>
      {children}
      <Link
        href="/"
        className="text-sm text-white underline underline-offset-4"
      >
        Back to skating
      </Link>
    </main>
  );
}

export function ClerkSetupNotice() {
  return (
    <section
      role="status"
      className="w-full max-w-sm rounded-2xl bg-white p-6 text-[#17181c] shadow-xl"
    >
      <h1 className="text-xl font-medium">Sign-in is being connected</h1>
      <p className="mt-3 text-sm leading-6 text-black/65">
        This app needs its existing Clerk application configuration before you
        can log in. You can still browse your footage while it is connected.
      </p>
    </section>
  );
}
