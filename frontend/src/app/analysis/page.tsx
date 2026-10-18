import { Suspense } from "react";
import { AnalysisScreen } from "@/components/experience/Screens";
export default function AnalysisPage() {
  return (
    <Suspense fallback={null}>
      <AnalysisScreen />
    </Suspense>
  );
}
