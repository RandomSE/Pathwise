import unittest

from pathwise.geom import Rect


class TestRoadStatesByIndex(unittest.TestCase):
    def test_build_road_states_by_index_groups_by_road(self):
        import main as game
        from pathwise.map import Road

        roads = [Road(Rect(0, 0, 100, 400), "vertical")]
        states = [
            {
                "road_index": 0,
                "direction": "vertical",
                "approach_rect": Rect(-50, -50, 200, 500),
            }
        ]
        grouped = game._build_road_states_by_index(states, len(roads))
        self.assertEqual(len(grouped[0]), 1)

    def test_road_states_for_car_uses_tagged_subset(self):
        import main as game

        game.road_states_by_index = [[{"road_index": 0}], []]

        class _CarStub:
            road_index = 0
            turn_signal = 0
            _turn_phase = "none"

        car = _CarStub()
        tagged = game._road_states_for_car(car, [{"fallback": True}])
        self.assertEqual(len(tagged), 1)
        car.road_index = 1
        fallback = game._road_states_for_car(car, [{"fallback": True}])
        self.assertEqual(fallback, [{"fallback": True}])

    def test_road_states_for_signaling_car_uses_tagged_subset(self):
        import main as game

        tagged = [{"road_index": 0, "crosswalk": "near"}]
        game.road_states_by_index = [tagged, []]
        fallback = [{"fallback": True}]

        class _CarStub:
            road_index = 0
            turn_signal = 1
            _turn_phase = "none"

        car = _CarStub()
        self.assertEqual(game._road_states_for_car(car, fallback), tagged)


if __name__ == "__main__":
    unittest.main()
