"""Narrator pacing regression tests; no Kokoro model download required."""
import ast
import re
import unittest
from pathlib import Path

source=Path("scripts/generate_kokoro_george.py").read_text(encoding="utf-8")
tree=ast.parse(source)
funcs=[node for node in tree.body
       if isinstance(node,ast.FunctionDef)
       and node.name in {"split_text","split_long_sentence","build_master_filter"}]
scope={"re":re}
exec(compile(ast.Module(body=funcs,type_ignores=[]),"narration_pacing", "exec"),scope)
split_text=scope["split_text"]
build_master_filter=scope["build_master_filter"]

class PacingTests(unittest.TestCase):
    def test_distinct_sentence_question_and_paragraph_breaks(self):
        content=("The room became very quiet. Nobody could explain the silence? "
                 "Even the clock seemed uncertain.\n\n"
                 "A different morning arrived. The question remained.")
        parts=split_text(content,limit=650, sentence_pause_ms=340,
                         paragraph_pause_ms=880,question_pause_ms=500)
        self.assertEqual([p["kind"] for p in parts],
                         ["sentence","question","paragraph","sentence","paragraph"])
        self.assertEqual([p["pause_ms"] for p in parts],
                         [340,500,880,340,880])
        self.assertEqual(" ".join(p["text"] for p in parts).count("clock"),1)

    def test_long_sentence_bounded_and_no_dropped_words(self):
        text="The quiet mind "+("remembers details that matter, " * 30)+"and learns."
        parts=split_text(text,limit=220)
        self.assertGreater(len(parts),2)
        self.assertTrue(all(len(part["text"]) <= 220 for part in parts))
        normalized=" ".join(" ".join(p["text"] for p in parts).split())
        self.assertEqual(normalized,text)

    def test_abbreviation_no_false_boundary(self):
        p=split_text("Dr. Smith understands uncertainty. We do too.\n\nYes.")
        self.assertEqual(len(p),3)
        self.assertTrue(p[0]["text"].startswith("Dr. Smith"))

    def test_mastering_optional(self):
        self.assertIsNone(build_master_filter("none"))
        filt=build_master_filter("gentle")
        self.assertIn("highpass=",filt)
        self.assertIn("loudnorm=",filt)
        self.assertIn("acompressor=",filt)

if __name__=="__main__":
    unittest.main()
