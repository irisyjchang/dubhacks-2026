import { Suspense } from "react";
import { isClerkConfigured } from "@/lib/auth-config";
import { HomeScreen } from "@/components/experience/Screens";
export default function HomePage() {
  return (
    <Suspense fallback={null}>
      <HomeScreen authEnabled={isClerkConfigured()} />
    </Suspense>
  );
}
