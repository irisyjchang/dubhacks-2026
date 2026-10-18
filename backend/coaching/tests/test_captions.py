import unittest

from spincoach.captions import caption_timeline,active_caption


class CaptionTests(unittest.TestCase):
    def test_boundaries_gaps_and_partial_final_second(self):
        report={'sections':[{'time_s':[0,1],'content':'Advice: Check arm height. Keep it soft.\nCue: A tray.'},
                            {'time_s':[1,1.93],'content':'Advice: Keep the leg tucked.\nCue: A ball.'},
                            {'time_s':[3,4],'content':'Observation: Not enough evidence.'}]}
        timeline=caption_timeline(report)
        self.assertEqual(active_caption(timeline,.99)['start_s'],0)
        self.assertEqual(active_caption(timeline,1)['start_s'],1)
        self.assertEqual(active_caption(timeline,1.9)['lines'],['Keep the leg tucked.'])
        self.assertIsNone(active_caption(timeline,1.93))
        self.assertIsNone(active_caption(timeline,3.5))
        self.assertEqual(timeline['captions'][0]['lines'],['Check arm height.'])

    def test_summaries_keep_model_source_and_provenance(self):
        content='Advice: Check your free-leg height.\nCue: A shelf.\nCaption: Check foot height | Picture a shelf'
        report={'sections':[{'time_s':[0,1],'content':content}]}
        self.assertEqual(caption_timeline(report)['captions'][0]['method'],'model caption')
        caption=caption_timeline(report,{0:['Check foot height','Cue: A shelf']})['captions'][0]
        self.assertEqual(caption['source_text'],content)
        self.assertEqual(caption['method'],'assistant summary of model advice and cue')
        self.assertEqual(caption_timeline(None)['captions'],[])
