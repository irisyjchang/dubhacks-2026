import { Suspense } from "react";
import { SignIn } from "@clerk/nextjs";
import { AuthPage, ClerkSetupNotice } from "@/components/auth/AuthPage";
import { isClerkConfigured } from "@/lib/auth-config";

export default function SignInPage() {
  return (
    <AuthPage>
      {isClerkConfigured() ? (
        <Suspense fallback={<p className="text-white">Loading sign-in…</p>}>
          <SignIn
            routing="path"
            path="/sign-in"
            signUpUrl="/sign-up"
            fallbackRedirectUrl="/"
          />
        </Suspense>
      ) : (
        <ClerkSetupNotice />
      )}
    </AuthPage>
  );
}
