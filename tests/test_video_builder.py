"""Offline regression tests for catalogue safety, bounded selection, fallback."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_video as b

def item(uid, semantic, *, url="https://cdn.pexels.com/video.mp4"):
    return {
        "uid":uid,"url":url,"page_url":"",
        "source":"pexels","title":semantic,
        "categories":["psychology"],"queries":[semantic],"tags":[],
        "semantic":semantic,"width":1280,"height":720,"duration":30
    }

class VideoBuilderTests(unittest.TestCase):
    def test_reject_offbrand_metadata(self):
        good = {"uid":"pexels:1","video_url":"https://videos.pexels.com/sample.mp4",
                "width":1920,"height":1080,"title":"lonely man walking in fog"}
        bad = {**good,"title":"women in bikini on beach"}
        self.assertIsNotNone(b.norm(good))
        self.assertIsNone(b.norm(bad))

    def test_plan_limits_unique_downloads(self):
        with tempfile.TemporaryDirectory() as root:
            t = Path(root)
            (t/"episode.json").write_text(json.dumps({
                "slug":"test","visuals":{"scene_seconds":12}
            }))
            (t/"word_timings.json").write_text(json.dumps({"cues":[
                {"start":0.,"end":100.,"text":"solitude shadow stoic fear power"}
            ]}))
            (t/"narration.mp3").write_bytes(b"fake")
            cat = [item(f"pexels:{i}",f"solitude shadow stoic fear power {i}")
                   for i in range(30)]
            with patch.object(b,"ffprobe",return_value=(100,0,0)), \
                 patch.object(b,"get_catalog",return_value=cat), \
                 patch.dict(os.environ,{"MAX_UNIQUE_CLIPS":"4"}):
                b.plan(t, "catalog.json")
            storyboard=json.loads((t/"storyboard.json").read_text())
            distinct={x["video"]["uid"] for x in storyboard["scenes"]}
            self.assertGreater(len(storyboard["scenes"]), 4)
            self.assertLessEqual(len(distinct),4)

    def test_oversize_source_skipped_before_downloading(self):
        class Response:
            status_code=200
            headers={"content-length":str(100*1024*1024)}
            def raise_for_status(self): pass
            def __enter__(self): return self
            def __exit__(self,*a): pass
        with tempfile.TemporaryDirectory() as root, \
             patch.object(b.requests,"get",return_value=Response()), \
             patch.dict(os.environ,{"MAX_STOCK_VIDEO_MB":"90"}):
            with self.assertRaisesRegex(ValueError,"too large"):
                b.fetch_video(item("pexels:big","shadow"),Path(root))
            self.assertFalse(list(Path(root).glob("*.mp4")))

    def test_failed_source_replaced_and_storyboard_updated(self):
        with tempfile.TemporaryDirectory() as root:
            t=Path(root)
            video=t/"source.mp4"
            video.write_bytes(b"fake source for mocked ffmpeg")
            (t/"narration.mp3").write_bytes(b"fake audio for mocked ffmpeg")
            (t/"captions.ass").write_text("fake captions")
            (t/"episode.json").write_text(json.dumps({
                "preview":True,"visuals":{"keywords":["shadow"]}
            }))
            bad=item("pexels:oversized","lonely shadow")
            fallback=item("pexels:okay","lonely shadow mirror")
            (t/"storyboard.json").write_text(json.dumps({
                "audio_duration":12.0,
                "scenes":[{"index":1,"seconds":12.0,
                           "topics":["shadow"],"narration":"the shadow",
                           "video":{k:v for k,v in bad.items() if k!="semantic"}}]
            }))
            def fake_fetch(candidate,_cache):
                if candidate["uid"]=="pexels:oversized":
                    raise ValueError("Source video too large")
                return video
            def fake_command(args,**kw):
                Path(args[-1]).write_bytes(b"fake rendered output")
            with patch.object(b,"get_catalog",return_value=[bad,fallback]), \
                 patch.object(b,"fetch_video",side_effect=fake_fetch), \
                 patch.object(b,"command",side_effect=fake_command), \
                 patch.object(b,"ffprobe",return_value=(12,1280,720)):
                b.render(t)
            sb=json.loads((t/"storyboard.json").read_text())
            self.assertEqual(sb["scenes"][0]["video"]["uid"],"pexels:okay")
            self.assertEqual(sb["scenes"][0]["replaced_unavailable_source"],"pexels:oversized")
            self.assertTrue((t/"video.mp4").exists())

    def test_episode_voice_pause_controls_are_preserved(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"input").mkdir()
            episode=root/"input"/"story.md"
            episode.write_text(
                "---\n"
                "title: Story\npreview: true\n"
                "voice:\n  speed: 0.86\n  mastering: gentle\n"
                "  pauses:\n    sentence_ms: 400\n    paragraph_ms: 950\n"
                "    question_ms: 600\n"
                "---\n"
                "This is a complete paragraph worth narrating, full of ideas.\n",
                encoding="utf-8"
            )
            with patch.object(b.Path,"cwd",return_value=root):
                b.parse_episode(episode,root/"build","")
            meta=json.loads((root/"build"/"episode.json").read_text())
            self.assertEqual(meta["voice"]["speed"],0.86)
            self.assertEqual(meta["voice"]["pauses"]["paragraph_ms"],950)
            self.assertEqual(meta["voice"]["pauses"]["question_ms"],600)
            self.assertEqual(meta["voice"]["mastering"],"gentle")

if __name__=="__main__":
    unittest.main()
