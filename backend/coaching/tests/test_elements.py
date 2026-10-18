import json
import tempfile
import unittest
from pathlib import Path

from spincoach.elements import phases_for,validate_markers,apply_element,motion_suggestion
from spincoach.element_feedback import local_element_assessment,finish_element_report
import test_kinematics as geometry_fixtures


class ElementTests(unittest.TestCase):
    def test_unmarked_jump_does_not_fabricate_flight(self):
        phases,events=phases_for({'duration_s':4},'waltz_jump',{})
        self.assertEqual(len(phases),1)
        self.assertIn('uncertain',phases[0]['name'])
        self.assertEqual(events,[])

    def test_user_marked_jump_phases_cover_the_clip_without_overlap(self):
        markers=validate_markers('waltz_jump',{'takeoff_s':1,'landing_s':1.6},4)
        phases,events=phases_for({'duration_s':4},'waltz_jump',markers)
        self.assertEqual([p['time_s'] for p in phases],[[0,1],[1,1.6],[1.6,4]])
        self.assertEqual([e['name'] for e in events],['Takeoff','Landing'])
        self.assertTrue(all('user' in p['source'] for p in phases))
        with self.assertRaises(ValueError):
            validate_markers('jump',{'takeoff_s':float('nan'),'landing_s':2},4)

    def test_ambiguous_pose_sequence_requires_confirmation(self):
        frames=[geometry_fixtures.KinematicsTests().frame(i) for i in range(60)]
        suggestion=motion_suggestion({'frames':frames},{'duration_s':2,'tracking':{'pose_coverage_pct':100}})
        self.assertEqual(suggestion['element'],'unknown')
        self.assertTrue(suggestion['requires_confirmation'])

    def test_plain_summary_phase_metrics_and_local_report_share_evidence(self):
        frames=[geometry_fixtures.KinematicsTests().frame(i) for i in range(60)]
        result={'duration_s':2,'tracking':{'pose_coverage_pct':100},
                'lowered_segment':{'start_s':.5,'end_s':1.5,'duration_s':1},
                'frames':[{'time_s':f['timestamp_ms']/1000,'phase':'lowered posture'} for f in frames]}
        apply_element(result,{'frames':frames},'sit_spin',{})
        element=result['element_analysis'];summary=element['summary']
        self.assertNotRegex(summary['line'],r'\d|°|degrees')
        ids={finding['id'] for finding in element['findings']}
        self.assertTrue(set(summary['good_evidence_ids']+summary['improve_evidence_ids'])<=ids)
        self.assertEqual(len(result['phase_kinematics']['windows']),3)
        with tempfile.TemporaryDirectory() as name:
            report=finish_element_report(local_element_assessment(result),result,name)
            text=(Path(name)/'coaching_report.md').read_text()
            self.assertIn(summary['good'],text)
            self.assertIn(summary['improve'],text)
            self.assertIn('Final coaching score: Not rated',text)
            self.assertEqual(len(text.strip().split('\n\n')),4)
            self.assertEqual(len(report['phase_details']),3)
            self.assertEqual(report['api_calls'],0)
            self.assertIn('sit_spin',json.dumps(report))
            for section in report['sections']:
                caption=section['content'].split('Caption:',1)[1]
                self.assertNotRegex(caption,r'\d|°')
