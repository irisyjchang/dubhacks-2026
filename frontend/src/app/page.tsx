import { Suspense } from "react";
import { HomeScreen } from "@/components/experience/Screens";
export default function HomePage() {
  return (
    <Suspense fallback={null}>
      <HomeScreen />
    </Suspense>
  );
}
