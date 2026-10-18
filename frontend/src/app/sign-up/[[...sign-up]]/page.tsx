import { Suspense } from "react";
import { SignUp } from "@clerk/nextjs";
import { AuthPage, ClerkSetupNotice } from "@/components/auth/AuthPage";
import { isClerkConfigured } from "@/lib/auth-config";

export default function SignUpPage() {
  return (
    <AuthPage>
      {isClerkConfigured() ? (
        <Suspense fallback={<p className="text-white">Loading sign-up…</p>}>
          <SignUp
            routing="path"
            path="/sign-up"
            signInUrl="/sign-in"
            fallbackRedirectUrl="/"
          />
        </Suspense>
      ) : (
        <ClerkSetupNotice />
      )}
    </AuthPage>
  );
}
