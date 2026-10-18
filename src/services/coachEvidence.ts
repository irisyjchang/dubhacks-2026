import type { AngleAnalysis, AngleData } from './angleAnalysisService';
import type { ManualMarkers } from '../store/analysisStore';

const joints = ['leftKneeFlexion', 'rightKneeFlexion', 'hipFlexion', 'shoulderAngleToIce'] as const;

export function buildCoachEvidence(user: AngleAnalysis | null, reference: AngleAnalysis | null, markers: ManualMarkers | null) {
  if (!user || !reference || !markers) return [];
  const closest = (values: AngleData[], time: number) => {
    const sample = values.reduce<AngleData | null>((best, next) =>
      !best || Math.abs(next.timestamp - time) < Math.abs(best.timestamp - time) ? next : best, null);
    return sample && Math.abs(sample.timestamp - time) <= 0.15 && Number.isFinite(sample.angle) ? sample : null;
  };
  const evidence = [];
  for (const phase of ['takeoff', 'landing'] as const) {
    const userTime = markers.user[`${phase}Time`];
    const referenceTime = markers.reference[`${phase}Time`];
    if (userTime === null || referenceTime === null) continue;
    for (const joint of joints) {
      const measured = closest(user[joint], userTime);
      const baseline = closest(reference[joint], referenceTime);
      if (!measured || !baseline) continue;
      evidence.push({
        phase, joint,
        timestamp: measured.timestamp,
        referenceTimestamp: baseline.timestamp,
        angle: Math.round(measured.angle * 10) / 10,
        referenceAngle: Math.round(baseline.angle * 10) / 10,
        difference: Math.round((measured.angle - baseline.angle) * 10) / 10,
      });
    }
  }
  return evidence;
}
