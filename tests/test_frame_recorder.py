import unittest

from analytics.frame_recorder import MAX_REPLAY_FRAMES, MAX_REPLAY_GAP_S, FrameRecorder
from pathwise.geom import Rect


class _CarStub:
    def __init__(self, x, y, spawn_id=0):
        self.rect = Rect(x, y, 40, 20)
        self.vertical = False
        self.archetype_index = 0
        self.current_speed = 2.0
        self.direction = 1
        self.turn_signal = 0

    def is_honking(self, _game_time):
        return False


class TestFrameRecorderCap(unittest.TestCase):
    def test_replay_frames_bounded(self):
        recorder = FrameRecorder(16)
        car = _CarStub(100, 100)
        player = Rect(90, 90, 20, 20)
        roads = []
        for i in range(MAX_REPLAY_FRAMES + 80):
            recorder.capture(
                i * 0.1,
                player,
                [car],
                roads,
                force=(i == 0),
                game_time=i * 0.1,
            )
        self.assertLessEqual(len(recorder.frames), MAX_REPLAY_FRAMES)

    def test_decision_frames_kept_when_trimming(self):
        recorder = FrameRecorder(16)
        car = _CarStub(100, 100)
        player = Rect(90, 90, 20, 20)
        recorder.capture_start(0.0, player, [car], [], game_time=0.0)
        recorder.queue_decision("commit")
        recorder.capture(0.5, player, [car], [], game_time=0.5)
        for i in range(MAX_REPLAY_FRAMES + 40):
            recorder.capture(1.0 + i * 0.08, player, [car], [], game_time=1.0 + i * 0.08)
        decision_frames = [f for f in recorder.frames if f.get("is_decision")]
        self.assertGreaterEqual(len(decision_frames), 1)
        self.assertLessEqual(len(recorder.frames), MAX_REPLAY_FRAMES)


    def test_trim_skips_index_zero(self):
        recorder = FrameRecorder(16)
        recorder.frames = [
            {"id": "f_00000", "seq": 0, "t": 0.0, "player": {}, "cars": [], "lights": [], "is_start": True},
            {"id": "f_00001", "seq": 1, "t": 0.5, "player": {}, "cars": [], "lights": []},
            {"id": "f_00002", "seq": 2, "t": 1.0, "player": {}, "cars": [], "lights": []},
        ]
        drop_idx = recorder._pick_trim_candidate()
        self.assertNotEqual(drop_idx, 0)

    def test_densify_frames_fills_large_gaps(self):
        recorder = FrameRecorder(16)
        car = _CarStub(100, 100)
        player = Rect(90, 90, 20, 20)
        recorder.frames = [
            {
                "id": "f_00000",
                "seq": 0,
                "t": 0.0,
                "player": {"x": 100, "y": 100, "s": 16},
                "cars": [],
                "lights": [],
                "is_decision": True,
            },
            {
                "id": "f_00001",
                "seq": 1,
                "t": 5.0,
                "player": {"x": 200, "y": 200, "s": 16},
                "cars": [],
                "lights": [],
                "is_decision": True,
            },
        ]
        recorder.densify_frames()
        gaps = [
            recorder.frames[i]["t"] - recorder.frames[i - 1]["t"]
            for i in range(1, len(recorder.frames))
        ]
        self.assertGreater(len(recorder.frames), 2)
        self.assertLessEqual(max(gaps), MAX_REPLAY_GAP_S + 0.01)


if __name__ == "__main__":
    unittest.main()
