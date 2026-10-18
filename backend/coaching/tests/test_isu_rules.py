import unittest

from spincoach.isu_rules import assess_rules,phase_rules,model_rule_problems,rule_lines
from spincoach.elements import apply_element
from spincoach.timeline_report import element_prompt
from spincoach.kinematics import response_problems
import test_kinematics as geometry_fixtures


class ISURuleTests(unittest.TestCase):
    def result(self,element='sit_spin'):
        frames=[geometry_fixtures.KinematicsTests().frame(i) for i in range(60)]
        result={'duration_s':2,'tracking':{'pose_coverage_pct':100},
                'lowered_segment':{'start_s':.5,'end_s':1.5,'duration_s':1},
                'frames':[{'time_s':f['timestamp_ms']/1000,'phase':'lowered posture'} for f in frames]}
        return apply_element(result,{'frames':frames},element,{'hold_start_s':.5,'hold_end_s':1.5})

    def test_rules_are_selected_for_element_with_pdf_page_references(self):
        assessment=self.result()['element_analysis']['isu_assessment']
        checks={c['id']:c for c in assessment['checks']}
        self.assertIn('SPIN-SIT',checks)
        self.assertNotIn('SPIN-CAMEL',checks)
        self.assertNotIn('JUMP-TAKEOFF',checks)
        self.assertEqual(checks['SPIN-SIT']['page'],14)
        self.assertTrue(checks['SPIN-SIT']['url'].endswith('#page=14'))
        self.assertEqual(checks['SPIN-SIT']['status'],'review_candidate')
        self.assertEqual(checks['SPIN-TOUCH']['status'],'not_assessable')
        self.assertIsNone(assessment['official_goe'])
        self.assertTrue(all(c['applied_reduction'] is None for c in checks.values()))
        self.assertIn('No reduction applied here','\n'.join(rule_lines(assessment)))

    def test_unmeasured_revolutions_never_become_missing_revolutions(self):
        analysis=self.result()['element_analysis']
        checks={c['id']:c for c in analysis['isu_assessment']['checks']}
        self.assertEqual(checks['SPIN-MISSING']['status'],'not_assessable')
        self.assertEqual(checks['SPIN-REVOLUTIONS']['status'],'not_assessable')
        self.assertIn('not turn counts',checks['SPIN-MISSING']['evidence_needed'])

    def test_hold_criteria_not_applied_to_entry_or_transition(self):
        analysis=self.result()['element_analysis']
        entry,hold,transition=analysis['phases']
        for phase in [entry,transition]:
            self.assertNotIn('SPIN-SIT',[c['id'] for c in phase_rules(analysis['isu_assessment'],phase)])
        self.assertIn('SPIN-SIT',[c['id'] for c in phase_rules(analysis['isu_assessment'],hold)])

    def test_no_universal_torso_threshold_for_upright_spin(self):
        result=self.result('upright_spin')
        self.assertFalse(any('upright body shape' in f['text'] for f in result['element_analysis']['findings']))
        check=next(c for c in result['element_analysis']['isu_assessment']['checks'] if c['id']=='SPIN-UPRIGHT')
        self.assertIn('skating leg',check['criterion'])

    def test_missing_tracking_cannot_pass_or_fail_position_rule(self):
        phases=[{'id':'p0','name':'Intended hold','time_s':[0,2]}]
        assessment=assess_rules('sit_spin','spin',phases,[{'cards':[]}],[])
        self.assertTrue(all(c['status']=='not_assessable' for c in assessment['checks']))

    def test_model_must_cite_a_supplied_rule_and_cannot_assign_a_score(self):
        refs=[{'id':'SPIN-SIT'}]
        self.assertEqual(model_rule_problems('Rule: SPIN-SIT\nAdvice: Check thigh depth in a side view.',refs),[])
        self.assertTrue(model_rule_problems('Rule: MADE-UP',refs))
        self.assertTrue(model_rule_problems('Rule: SPIN-SIT\nGOE: -2',refs))
        self.assertTrue(model_rule_problems('Rule: SPIN-SIT\nThis is a legal sit position.',refs))
        self.assertTrue(model_rule_problems('Rule: SPIN-SIT\nThe skater violates the rule.',refs))
        self.assertTrue(model_rule_problems('Rule: SPIN-SIT',[]))

    def test_rule_advice_does_not_have_to_repeat_unrelated_angles(self):
        result=self.result()
        window=result['phase_kinematics']['windows'][1]
        raw=('Rule: SPIN-SIT\nObservation: Your {M1} and {M2} describe this projected shape.\n'
             'Advice: Use a side view to check skating-thigh depth relative to the ice; the skating leg is unverified.\n'
             'Cue: Check thigh against ice.\nCaption: Check thigh depth | Thigh against ice')
        self.assertEqual(response_problems(raw,window,require_advice_measurement=False),[])
        self.assertTrue(response_problems(raw,window))

    def test_unknown_and_waltz_are_not_given_fabricated_scoring_rules(self):
        unknown=assess_rules('unknown','unknown',[],[],[])
        self.assertEqual(unknown['checks'],[])
        jump=assess_rules('waltz_jump','jump',[],[],[])
        self.assertEqual({c['id'] for c in jump['checks']},{'JUMP-LANDING','JUMP-TAKEOFF'})
        self.assertIsNone(jump['base_value'])
        self.assertIn('developmental',jump['policy'])

    def test_model_prompt_prioritizes_position_rule_for_hold(self):
        analysis=self.result()['element_analysis']
        phase=analysis['phases'][1]
        facts={'phase':phase,'confirmed_element':analysis['label'],
               'shared_findings':analysis['findings'],'measurement_cards':[],
               'measurement_limits':'2D estimates only'}
        prompt=element_prompt(facts,phase_rules(analysis['isu_assessment'],phase))
        self.assertIn('Rule: SPIN-SIT\nObservation:',prompt)
        self.assertIn('not use torso lean or a knee joint angle as a substitute',prompt)
        self.assertNotIn('SPIN-EXIT',prompt)


if __name__=='__main__':
    unittest.main()
