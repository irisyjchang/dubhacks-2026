import { Suspense } from "react";
import { AnalysisScreen } from "@/components/experience/Screens";
export default function PlanPage() {
  return (
    <Suspense fallback={null}>
      <AnalysisScreen />
    </Suspense>
  );
}
