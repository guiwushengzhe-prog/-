import io
import math
import unittest

import mido

from piano.music import (PALETTE, build_project, demo_project, group_onsets, numbered_pitch,
                         read_midi, validate_notes, write_midi)
from piano.server import SerialLights


class MusicTests(unittest.TestCase):
    def test_numbered_score_pitch_and_octave(self):
        self.assertEqual(numbered_pitch(60, 0), {"degree": "1", "octave": 0})
        self.assertEqual(numbered_pitch(59, 0), {"degree": "7", "octave": -1})
        self.assertEqual(numbered_pitch(61, 0), {"degree": "#1", "octave": 0})
        self.assertEqual(numbered_pitch(62, 2), {"degree": "1", "octave": 0})
        self.assertEqual(numbered_pitch(74, 2), {"degree": "1", "octave": 1})

    def test_tempo_changes_and_simultaneous_notes_survive_midi(self):
        midi = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.extend([
            mido.MetaMessage("set_tempo", tempo=500000),
            mido.Message("note_on", note=60, velocity=90),
            mido.Message("note_on", note=64, velocity=70),
            mido.MetaMessage("set_tempo", tempo=1000000, time=480),
            mido.Message("note_off", note=60, time=480),
            mido.Message("note_off", note=64),
        ])
        stream = io.BytesIO()
        midi.save(file=stream)
        notes, bpm, _ = read_midi(stream.getvalue())
        self.assertEqual(bpm, 120)
        self.assertEqual([n["start"] for n in notes], [0, 0])
        self.assertEqual([n["end"] for n in notes], [1.5, 1.5])
        self.assertEqual([n["source_beat_duration"] for n in notes], [2, 2])
        recovered, _, _ = read_midi(write_midi({"notes": notes}))
        self.assertEqual([(n["pitch"], n["start"], n["end"]) for n in recovered],
                         [(n["pitch"], n["start"], n["end"]) for n in notes])

    def test_invalid_timestamps_and_duplicate_ids_are_rejected(self):
        for end in [math.inf, math.nan, -1, 0]:
            with self.assertRaises(ValueError):
                validate_notes([{"pitch": 60, "start": 0, "end": end}])
        with self.assertRaises(ValueError):
            validate_notes([{"id": "a", "pitch": 60, "start": 0, "end": 1}] * 2)

    def test_explicit_hand_labels_survive_import_and_crossed_hands(self):
        midi = mido.MidiFile(ticks_per_beat=480)
        # Deliberately cross the hands: pitch alone must not override the score.
        for label, pitch in (("Left Hand", 76), ("RH", 48)):
            track = mido.MidiTrack([
                mido.MetaMessage("track_name", name=label),
                mido.Message("note_on", note=pitch, velocity=90),
                mido.Message("note_off", note=pitch, time=480)])
            midi.tracks.append(track)
        stream = io.BytesIO()
        midi.save(file=stream)
        notes, bpm, info = read_midi(stream.getvalue())
        self.assertEqual(info["hand_labelled_notes"], 2)
        project = build_project(notes, bpm=bpm, transcription=info)
        self.assertEqual({n["pitch"]: n["hand"] for n in project["notes"]},
                         {76: "L", 48: "R"})
        self.assertEqual({n["source_track_name"] for n in project["source_notes"]},
                         {"Left Hand", "RH"})

    def test_track_number_and_channel_do_not_imply_a_hand(self):
        midi = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack([
            mido.MetaMessage("track_name", name="Bright Piano"),
            mido.Message("note_on", channel=1, note=48, velocity=90),
            mido.Message("note_off", channel=1, note=48, time=480)])
        midi.tracks.append(track)
        stream = io.BytesIO()
        midi.save(file=stream)
        notes, _, info = read_midi(stream.getvalue())
        self.assertEqual(info["hand_labelled_notes"], 0)
        self.assertNotIn("source_hand", notes[0])
        self.assertEqual(notes[0]["source_channel"], 1)
        self.assertEqual(notes[0]["source_track"], 0)

    def test_overlapping_tracks_keep_note_on_provenance(self):
        midi = mido.MidiFile(ticks_per_beat=480)
        for name, start, duration in (("RH", 0, 960), ("LH", 240, 240)):
            midi.tracks.append(mido.MidiTrack([
                mido.MetaMessage("track_name", name=name),
                mido.Message("note_on", note=60, velocity=90, time=start),
                mido.Message("note_off", note=60, time=duration)]))
        stream = io.BytesIO()
        midi.save(file=stream)
        notes, _, _ = read_midi(stream.getvalue())
        self.assertEqual({n["source_hand"]: (n["start"], n["end"]) for n in notes},
                         {"L": (.25, .5), "R": (0, 1)})

    def test_note_off_in_another_track_remains_supported(self):
        midi = mido.MidiFile(ticks_per_beat=480)
        midi.tracks.extend([
            mido.MidiTrack([mido.MetaMessage("track_name", name="LH"),
                           mido.Message("note_on", note=48, velocity=90)]),
            mido.MidiTrack([mido.Message("note_off", note=48, time=480)])])
        stream = io.BytesIO()
        midi.save(file=stream)
        notes, _, _ = read_midi(stream.getvalue())
        self.assertEqual((notes[0]["start"], notes[0]["end"], notes[0]["source_hand"]),
                         (0, .5, "L"))

    def test_fingers_lights_and_score_use_same_note(self):
        project = demo_project()
        self.assertTrue(project["notes"])
        for note in project["notes"]:
            self.assertIn(note["finger"], range(1, 6))
            self.assertIn(note["hand"], ("R", "L"))
            self.assertEqual(note["color"], PALETTE[note["hand"] + str(note["finger"])])
            self.assertEqual(note["jianpu"], numbered_pitch(note["pitch"], project["tonic"]))
        for group in project["groups"]:
            members = [n for n in project["notes"] if n["id"] in group["note_ids"]]
            for hand in ("R", "L"):
                fingers = [n["finger"] for n in members if n["hand"] == hand]
                self.assertEqual(len(fingers), len(set(fingers)))

    def test_chord_group_preserves_simultaneity(self):
        groups = group_onsets([{"id": "c", "start": 0}, {"id": "e", "start": .02},
                               {"id": "g", "start": .024}, {"id": "d", "start": .6}])
        self.assertEqual(groups[0]["note_ids"], ["c", "e", "g"])
        self.assertEqual(len(groups), 2)


class FakePort:
    is_open = True
    def __init__(self):
        self.sent = []
    def write(self, data):
        self.sent.append(data)
    def close(self):
        self.is_open = False


class SerialProtocolTests(unittest.TestCase):
    def test_sparse_frame_passes_brightness_and_disconnect_clears(self):
        import json
        controller = SerialLights()
        port = FakePort()
        controller.port = port
        controller.frame({"pixels": [{"index": 12, "r": 255, "g": 4, "b": 0}],
                          "brightness": .9})
        frame = json.loads(port.sent[-1])
        self.assertEqual(frame["pixels"], [[12, 255, 4, 0]])
        self.assertEqual(frame["brightness"], .9)
        controller.disconnect()
        self.assertEqual(json.loads(port.sent[-1]), {"type": "clear"})
        self.assertFalse(port.is_open)

    def test_invalid_frames_do_not_write(self):
        controller = SerialLights()
        port = FakePort()
        controller.port = port
        for pixels in [[[512, 255, 0, 0]], [[-1, 0, 0, 0]], [[0, 256, 0, 0]], [[0, 0.5, 0, 0]]]:
            with self.assertRaises(ValueError):
                controller.frame({"pixels": pixels})
        self.assertEqual(port.sent, [])


if __name__ == "__main__":
    unittest.main()
