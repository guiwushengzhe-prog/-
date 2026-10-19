import unittest

from piano.music import read_midi
from piano.phrase_worker import make_midi, sections_from_candidates


def score(pitches):
    notes = [{"id": str(i), "pitch": pitch, "start": i * .5,
              "end": i * .5 + .4, "velocity": 80} for i, pitch in enumerate(pitches)]
    return {"notes": notes, "bpm": 120, "duration": len(notes) * .5,
            "groups": [{"time": n["start"], "note_ids": [n["id"]]} for n in notes]}


class PhraseTests(unittest.TestCase):
    def test_full_passage_validation_and_complete_coverage(self):
        project = score([60, 62, 64, 65, 60, 62, 64, 65, 70, 72])
        result = sections_from_candidates(project, [(0, 2), (2, 4)], lambda t: t * 2, 4)
        repeated = [s for s in result if s["kind"] == "repeat"]
        self.assertEqual(len(repeated), 1)
        self.assertEqual(len(repeated[0]["occurrences"]), 2)
        coverage = [0] * len(project["groups"])
        for section in result:
            for value in section["occurrences"]:
                self.assertGreater(value["end"], value["start"])
                for i in range(value["startGroup"], value["endGroup"]):
                    coverage[i] += 1
        self.assertEqual(coverage, [1] * len(coverage))
        project["notes"][5]["pitch"] = 63
        self.assertFalse(any(s["kind"] == "repeat" for s in sections_from_candidates(
            project, [(0, 2), (2, 4)], lambda t: t * 2, 4)), "首尾相同、内部不同不能合并")

    def test_note_duration_changes_are_not_identical_repeats(self):
        project = score([60, 62, 60, 62])
        project["notes"][2]["end"] -= .2
        result = sections_from_candidates(project, [(0, 1), (1, 2)], lambda t: t * 2, 4)
        self.assertFalse(any(s["kind"] == "repeat" for s in result))

    def test_meter_and_variable_tempo_survive_analysis_export(self):
        project = score([60, 64])
        project["tempo_map"] = [{"time": 0, "beat": 0, "tempo": 500000},
                                {"time": .5, "beat": 1, "tempo": 1000000}]
        project["time_signature_map"] = [{"time": 0, "beat": 0, "numerator": 3, "denominator": 8}]
        data, _ = make_midi(project)
        notes, _, metadata = read_midi(data)
        self.assertEqual(metadata["time_signature_map"], project["time_signature_map"])
        self.assertEqual(metadata["tempo_map"], project["tempo_map"])
        for before, after in zip(project["notes"], notes):
            self.assertAlmostEqual(before["start"], after["start"], places=3)
            self.assertAlmostEqual(before["end"], after["end"], places=3)
