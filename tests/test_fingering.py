"""Physical-invariant and score-conservation tests for automatic fingering.

Run from the app root: python -m unittest discover -s tests -p 'test_fingering.py'
Also runs standalone beside the adapter research deliverable.
"""
from __future__ import annotations

import copy
from pathlib import Path
import random
import sys
import unittest

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
if (APP_ROOT / "piano").is_dir():
    from piano.fingering import annotate, key_x, _chord_assignments, _verify_assignments
    from piano.vendor.pianoplayer.hand import Hand
else:
    from fingering import annotate, key_x, _chord_assignments, _verify_assignments
    from vendor.pianoplayer.hand import Hand


def sequence(pitches, *, chord=False, duration=0.4):
    return [{"id": str(i), "pitch": pitch,
             "start": 0.0 if chord else i * 0.5,
             "end": (0.0 if chord else i * 0.5) + duration,
             "velocity": 90}
            for i, pitch in enumerate(pitches)]


class FingeringTests(unittest.TestCase):
    def assert_physical(self, source, out, metadata, hand_size="M"):
        self.assertEqual(metadata["source_note_count"], len(source))
        self.assertEqual(len(out) + metadata["omitted_note_count"], len(source))
        self.assertEqual(len({n["id"] for n in out}), len(out))
        self.assertEqual({n["id"] for n in out} | {n["id"] for n in metadata["omitted_notes"]},
                         {n["id"] for n in source})
        lookup = {n["id"]: n for n in out}
        for n in out:
            self.assertIn(n["hand"], ("R", "L"))
            self.assertIn(n["finger"], (1, 2, 3, 4, 5))
            self.assertGreater(n["end"], n["start"])
            self.assertIsInstance(n["onset_group"], int)
        for i, a in enumerate(out):
            for b in out[i + 1:]:
                if b["start"] >= a["end"] - 1e-9:
                    break
                if a["hand"] != b["hand"]:
                    continue
                if min(a["end"], b["end"]) <= max(a["start"], b["start"]) + 1e-9:
                    continue
                self.assertNotEqual(a["finger"], b["finger"])
                direction = 1 if a["hand"] == "R" else -1
                self.assertGreater((a["pitch"] - b["pitch"]) *
                                   (a["finger"] - b["finger"]) * direction, 0)
                self.assertLessEqual(abs(key_x(a["pitch"]) - key_x(b["pitch"])),
                                     21 * Hand.size_factor(hand_size) + 1e-8)
        for n in metadata["trimmed_notes"]:
            self.assertEqual(lookup[n["id"]]["end"], n["practice_end"])
            self.assertGreater(n["source_end"], n["practice_end"])
        changed = {n["id"] for n in metadata["omitted_notes"] + metadata["trimmed_notes"]}
        self.assertEqual(metadata["simplified_count"], len(changed))
        self.assertEqual(metadata["fingering_kind"], "automatic_practice_suggestion")

    def run_case(self, notes, size="M"):
        before = copy.deepcopy(notes)
        out, metadata, warnings = annotate(notes, hand_size=size)
        self.assertEqual(before, notes, "fingering must not overwrite source events")
        self.assert_physical(notes, out, metadata, size)
        if metadata["simplified_count"]:
            self.assertTrue(warnings)
            self.assertEqual(metadata["arrangement"], "simplified_practice")
        return out, metadata, warnings

    def test_c_major_up_and_down(self):
        out, metadata, _ = self.run_case(sequence([60, 62, 64, 65, 67, 69, 71, 72,
                                                  71, 69, 67, 65, 64, 62, 60]))
        self.assertEqual([n["finger"] for n in out], [1, 2, 3, 1, 2, 3, 4, 5,
                                                     4, 3, 2, 1, 3, 2, 1])
        self.assertEqual({n["hand"] for n in out}, {"R"})
        self.assertEqual(metadata["simplified_count"], 0)

    def test_triad(self):
        _, metadata, _ = self.run_case(sequence([60, 64, 67], chord=True))
        self.assertEqual(metadata["omitted_note_count"], 0)

    def test_valid_upstream_chord_is_preserved(self):
        notes = sequence([60, 64, 67], chord=True)
        hand = Hand([], side="right", size="M")
        proposals = {notes[0]["id"]: 2, notes[1]["id"]: 3, notes[2]["id"]: 5}
        _, assigned, _ = _chord_assignments(notes, [], "R", proposals, hand, None, None)
        self.assertEqual([n["finger"] for n in assigned], [2, 3, 5])

    def test_upstream_chord_conflicting_with_held_note_is_repaired(self):
        notes = sequence([64, 67], chord=True)
        held = [{"id": "held", "pitch": 60, "start": 0, "end": 2,
                 "finger": 1, "hand": "R"}]
        hand = Hand([], side="right", size="M")
        _, assigned, _ = _chord_assignments(notes, held, "R",
                                            {notes[0]["id"]: 1, notes[1]["id"]: 3},
                                            hand, None, None)
        self.assertNotIn(1, [n["finger"] for n in assigned])
        _verify_assignments(held + assigned, hand.max_span_cm)

    def test_final_validation_rejects_overlapping_finger_reuse(self):
        notes = [{"id": "a", "pitch": 60, "start": 0, "end": 2,
                  "finger": 2, "hand": "R"},
                 {"id": "b", "pitch": 64, "start": 1, "end": 1.5,
                  "finger": 2, "hand": "R"}]
        with self.assertRaisesRegex(ValueError, "同一手指"):
            _verify_assignments(notes, 21)

    def test_separated_two_hands(self):
        out, metadata, _ = self.run_case(sequence([36, 40, 43, 72, 76, 79], chord=True))
        self.assertEqual([n["hand"] for n in out], ["L"] * 3 + ["R"] * 3)
        self.assertEqual(metadata["simplified_count"], 0)

    def test_repeated_pitch(self):
        out, metadata, _ = self.run_case(sequence([60] * 12))
        self.assertEqual(len({n["finger"] for n in out}), 1)
        self.assertEqual(metadata["simplified_count"], 0)

    def test_twelve_note_chord_is_accounted_for(self):
        out, metadata, _ = self.run_case(sequence(range(48, 60), chord=True))
        self.assertEqual(len(out), 10)
        self.assertEqual(metadata["omitted_note_count"], 2)
        self.assertIn(48, [n["pitch"] for n in out])
        self.assertIn(59, [n["pitch"] for n in out])

    def test_extreme_keyboard_span(self):
        _, metadata, _ = self.run_case(sequence([21, 45, 69, 108], chord=True))
        self.assertGreater(metadata["omitted_note_count"], 0)

    def test_acoustic_tails_release_before_finger_reuse(self):
        _, metadata, _ = self.run_case(sequence([60, 62, 64, 65, 67, 69, 71, 72], duration=3))
        self.assertGreater(metadata["trimmed_note_count"], 0)

    def test_asymmetric_five_note_chord_can_use_both_hands(self):
        _, metadata, _ = self.run_case(sequence([60, 61, 62, 64, 71], chord=True))
        self.assertEqual(metadata["omitted_note_count"], 0)

    def test_seeded_random_cases_for_seven_hand_sizes(self):
        rng = random.Random(104)
        for size in ("XXS", "XS", "S", "M", "L", "XL", "XXL"):
            for case in range(20):
                with self.subTest(size=size, case=case):
                    notes = []
                    for group in range(10):
                        for pitch in sorted(rng.sample(range(21, 109), rng.randint(1, 13))):
                            notes.append({"id": str(len(notes)), "pitch": pitch,
                                          "start": group * .5,
                                          "end": group * .5 + rng.choice((.4, 1.8)),
                                          "velocity": 90})
                    self.run_case(notes, size)


if __name__ == "__main__":
    unittest.main()
