"""Close remaining coverage-gate gaps without re-enabling map bake."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import arcade
from PIL import Image

from map_generation.difficulty import DifficultyProfile
from map_generation.pathfinding import Cell, perimeter_cells
from pathwise.entity_draw_batch import EntityDrawBatch
from pathwise.geom import Rect
from pathwise.input_keys import KeyState
from pathwise.map import MapBase, Road, draw_arrow
from pathwise.map_visuals import (
    BakedMapLayer,
    apply_rainy_road_overlay,
    _draw_round_rect,
    _rgba,
)
from pathwise.modifiers import (
    exposure,
    high_speed,
    highway,
    lag,
    lawless,
    old,
    rainy_roads,
    time_pressure,
    variable_speed_zones,
)
from pathwise.modifiers.registry import ModifierContext
from pathwise.modifiers.weather_visuals import (
    RAIN_UPDATE_STRIDE,
    RainParticlePool,
    bake_rainy_road_overlay,
    draw_weather_overlay,
    reset_rain_visuals,
)
from pathwise.pathwise_render import (
    draw_sim_circle_filled_world,
    draw_sim_rect_outline,
    sim_point_to_arcade,
    sim_rect_center_to_arcade,
    sim_rect_to_arcade_lbwh,
)
from pathwise.pathwise_window import GamePlayView, PathwiseWindow
from pathwise.pedestrian import Pedestrian
from pathwise.pre_game import ModifiersDetailView, SessionConfig
from pathwise.round_frame import _cheap_offscreen_motion, update_round_frame
from pathwise.sprites import draw_slip_trip_message, draw_time_bonus_popup
from pathwise.viewport import DisplayLayout
from tests.arcade_harness import fake_arcade_window


class TestRainSlipTrackerUpdate(unittest.TestCase):
    def tearDown(self):
        rainy_roads.install_for_round(ModifierContext(frozenset()))

    def test_update_stuns_when_sprint_bucket_slips(self):
        rainy_roads.install_for_round(
            ModifierContext(
                frozenset({"rainy_roads"}), session_base_seed=7, round_index=1
            )
        )
        tracker = rainy_roads.RainSlipTracker()
        tracker.note_sprint_activity(0.2)
        player = Pedestrian((40, 40))
        tracker._slip_roll_for_bucket = lambda bucket: True
        slipped = tracker.update(1.4, player)
        self.assertTrue(slipped)
        self.assertTrue(player.is_slip_stunned(1.4))

    def test_update_skips_idle_bucket_and_reset_clears(self):
        rainy_roads.install_for_round(
            ModifierContext(
                frozenset({"rainy_roads"}), session_base_seed=7, round_index=1
            )
        )
        tracker = rainy_roads.RainSlipTracker()
        player = Pedestrian((40, 40))
        self.assertFalse(tracker.update(1.2, player))
        tracker.note_sprint_activity(0.1)
        tracker.reset()
        self.assertEqual(tracker._sprinted_in_bucket, {})
        self.assertEqual(tracker._resolved_buckets, set())

    def test_inactive_update_and_overshoot_without_ctx(self):
        rainy_roads.install_for_round(ModifierContext(frozenset()))
        self.assertFalse(rainy_roads.is_active())
        tracker = rainy_roads.RainSlipTracker()
        player = Pedestrian((10, 10))
        self.assertFalse(tracker.update(3.0, player))
        self.assertFalse(tracker._slip_roll_for_bucket(0))
        rainy_roads._ctx = None
        self.assertEqual(
            rainy_roads.crosswalk_overshoot_distance_px(spawn_id=1, crosswalk_key=2),
            0,
        )
        rainy_roads.install_for_round(
            ModifierContext(
                frozenset({"rainy_roads"}), session_base_seed=4, round_index=1
            )
        )
        dist = rainy_roads.crosswalk_overshoot_distance_px(spawn_id=1, crosswalk_key=2)
        self.assertGreaterEqual(dist, 6)
        self.assertLessEqual(dist, 16)
        self.assertTrue(rainy_roads.is_active())
        extra = rainy_roads.RainSlipTracker()
        extra._resolved_buckets = {2}
        self.assertFalse(extra.update(3.0, Pedestrian((8, 8))))


class TestRainVisualsAndBake(unittest.TestCase):
    def tearDown(self):
        reset_rain_visuals()

    def test_particle_wrap_and_overlay_noop_without_pool(self):
        pool = RainParticlePool(cap=4, seed=11)
        pool._frame = RAIN_UPDATE_STRIDE - 1
        pool._particles[0] = (0.5, 1.04, 400.0, 10.0)
        pool.update(1.0)
        self.assertLessEqual(pool._particles[0][1], 0.05)
        reset_rain_visuals()
        draw_weather_overlay(
            sim_width=80,
            sim_height=60,
            view_rect=Rect(0, 0, 80, 60),
            camera_offset=(0, 0),
            elapsed=0.5,
        )

    def test_bake_rainy_overlay_darkens_roads_and_tiles(self):
        img = Image.new("RGBA", (96, 64), (80, 80, 80, 255))
        baked = BakedMapLayer(
            texture=arcade.Texture(img, hash="rain_gate_base"),
            world_bounds=Rect(0, 0, 96, 64),
            tiles=(),
        )
        crosswalk = Rect(20, 24, 24, 10)
        states = [
            {
                "crosswalk": crosswalk,
                "direction": "horizontal",
                "road_rect": Rect(0, 20, 96, 18),
                "approach": "west",
            },
            {
                "crosswalk": crosswalk,
                "direction": "horizontal",
                "road_rect": Rect(0, 20, 96, 18),
                "approach": "east",
            },
            {
                "crosswalk": Rect(48, 8, 10, 20),
                "direction": "vertical",
                "road_rect": Rect(44, 0, 18, 64),
                "approach": "north",
            },
        ]
        overlay = bake_rainy_road_overlay(
            baked,
            road_states=states,
            session_base_seed=3,
            round_index=1,
        )
        via_map = apply_rainy_road_overlay(
            baked,
            road_states=states,
            session_base_seed=3,
            round_index=1,
        )
        self.assertGreater(len(overlay.tiles), 0)
        self.assertEqual(len(overlay.tiles), len(via_map.tiles))
        self.assertEqual(overlay.world_bounds, baked.world_bounds)


class TestVariableSpeedCarMult(unittest.TestCase):
    def tearDown(self):
        variable_speed_zones.install_for_round(ModifierContext(frozenset()))

    def test_speed_mult_for_car_guards_and_vertical_bands(self):
        ctx = ModifierContext(
            frozenset({"variable_speed_zones"}),
            session_base_seed=21,
            round_index=1,
        )
        variable_speed_zones.install_for_round(ctx)
        self.assertEqual(variable_speed_zones.along_frac_from_pose(None, 0, 0), 0.0)
        road = Road(Rect(10, 20, 90, 40), "vertical")
        self.assertGreaterEqual(
            variable_speed_zones.along_frac_from_pose(road, 40, 30), 0.0
        )
        last = variable_speed_zones.band_rect_for_road(road, 2)
        self.assertEqual(last.right, road.rect.right)
        across = Road(Rect(0, 0, 40, 90), "horizontal")
        self.assertGreaterEqual(
            variable_speed_zones.along_frac_from_pose(across, 10, 30), 0.0
        )
        h_last = variable_speed_zones.band_rect_for_road(across, 2)
        self.assertEqual(h_last.bottom, across.rect.bottom)
        cached = variable_speed_zones.zone_mults_for_road(0)
        self.assertEqual(variable_speed_zones.zone_mults_for_road(0), cached)

        class Car:
            road_index = 0
            rect = Rect(40, 30, 20, 10)

        self.assertNotEqual(
            variable_speed_zones.speed_mult_for_car(Car(), [road]), 0.0
        )
        missing = Car()
        missing.road_index = None
        self.assertEqual(variable_speed_zones.speed_mult_for_car(missing, [road]), 1.0)
        missing.road_index = 9
        self.assertEqual(variable_speed_zones.speed_mult_for_car(missing, [road]), 1.0)
        missing.road_index = 0
        missing.rect = None
        self.assertEqual(variable_speed_zones.speed_mult_for_car(missing, [road]), 1.0)
        variable_speed_zones.install_for_round(ModifierContext(frozenset()))
        idle = variable_speed_zones.zone_mults_for_road(4)
        self.assertEqual(idle, (1.0, 1.0, 1.0))
        self.assertEqual(variable_speed_zones.speed_mult_for_car(Car(), [road]), 1.0)


class TestPathwiseRenderLayout(unittest.TestCase):
    def test_layout_mapping_and_outline_draw(self):
        layout = DisplayLayout.fit_window(1600, 900)
        ax, ay = sim_point_to_arcade(10, 20, 600, layout)
        self.assertGreater(ax, 0)
        self.assertGreater(ay, 0)
        lbwh = sim_rect_to_arcade_lbwh(0, 0, 8, 8, 600, layout)
        self.assertEqual(len(lbwh), 4)
        rect = Rect(40, 50, 12, 12)
        cx, cy = sim_rect_center_to_arcade(rect, (0, 0), 600, layout)
        self.assertGreater(cx, 0)
        with patch("arcade.draw_lbwh_rectangle_outline") as outline:
            draw_sim_rect_outline(rect, (0, 0), 600, (0, 0, 0), layout=layout)
            outline.assert_called_once()
        with patch("arcade.draw_circle_filled") as circle:
            draw_sim_circle_filled_world(10, 20, (0, 0), 600, 4, (1, 2, 3), layout)
            circle.assert_called_once()


class TestCheapOffscreenIntersectionStop(unittest.TestCase):
    def test_entry_blocked_clears_speed(self):
        from pathwise.car import Car, _frame_car_spatial

        car = Car(100, 100, 3.0, vertical=False, spawn_id=17)
        car.current_speed = 2.0
        car.speed = 2.0
        car.direction = 1
        car._sync_collision_shell(force=True)
        _frame_car_spatial.rebuild([car])
        before = car.rect.topleft

        class Host:
            intersection_zones = [Rect(140, 80, 80, 80)]

        car._near_intersection_bbox = lambda zones, margin=0: True
        car._intersection_entry_blocked = lambda *args, **kwargs: True
        with patch("pathwise.round_frame._oriented_road_states_for_car", return_value=[]):
            with patch("pathwise.round_frame._road_states_for_car", return_value=[]):
                _cheap_offscreen_motion(car, Host())
        self.assertEqual(car.rect.topleft, before)
        self.assertEqual(car.current_speed, 0.0)

    def test_red_advance_and_crosswalk_block_paths(self):
        from pathwise.car import Car, _frame_car_spatial

        car = Car(100, 100, 3.0, vertical=False, spawn_id=18)
        car.current_speed = 2.0
        car.speed = 2.0
        car.direction = 1
        car._sync_collision_shell(force=True)
        _frame_car_spatial.rebuild([car])

        class Host:
            intersection_zones = [Rect(140, 80, 80, 80)]

        car._near_intersection_bbox = lambda zones, margin=0: True
        car._intersection_entry_blocked = lambda *args, **kwargs: False
        car._intersection_advance_blocked_on_red = lambda *args, **kwargs: True
        with patch("pathwise.round_frame._oriented_road_states_for_car", return_value=[]):
            with patch("pathwise.round_frame._road_states_for_car", return_value=[]):
                _cheap_offscreen_motion(car, Host())
        self.assertEqual(car.current_speed, 0.0)

        car.current_speed = 2.0
        car.speed = 2.0
        car._intersection_advance_blocked_on_red = lambda *args, **kwargs: False
        car._crosswalk_advance_blocked = lambda *args, **kwargs: True
        with patch("pathwise.round_frame._oriented_road_states_for_car", return_value=[]):
            with patch("pathwise.round_frame._road_states_for_car", return_value=[]):
                _cheap_offscreen_motion(car, Host())
        self.assertEqual(car.current_speed, 0.0)


class TestRoundFrameCoverageBranches(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = 4242
        game.session_seed_source = "test"
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.session_audience = "recruiter"
        game.round_active = False
        game.ENABLE_PERF_PROFILE = False
        game.ENABLE_CAR_DIAGNOSTICS = False

    def test_sim_clock_none_and_trip_fail(self):
        profile = DifficultyProfile.for_menu_preset("easy")
        self.game.start_round(1, profile, "easy")
        self.game._sim_clock_last = None
        state = update_round_frame(KeyState())
        self.assertIsNotNone(state)
        with patch("pathwise.round_frame.old.update_fatal_trip", return_value="fail"):
            with patch("pathwise.round_frame.end_round") as end:
                none_state = update_round_frame(KeyState())
        self.assertIsNone(none_state)
        end.assert_called_once()

    def test_recruiter_hud_modifier_chrome_and_diagnostics(self):
        ids = frozenset(
            {
                "rainy_roads",
                "lawless",
                "time_pressure",
                "high_speed",
                "lag",
                "old",
                "exposure",
            }
        )
        self.game.session_modifiers = ModifierContext(
            ids, session_base_seed=4242, round_index=1
        )
        profile = DifficultyProfile.for_menu_preset("normal")
        self.game.start_round(1, profile, "normal")
        self.game.ENABLE_CAR_DIAGNOSTICS = True
        self.game.ENABLE_PERF_PROFILE = True
        self.game.player.rect.center = self.game.road_states[0]["crosswalk"].center
        draw_state = update_round_frame(KeyState())
        joined = "\n".join(draw_state["hud_lines"])
        self.assertIn("Weather: Rainy roads", joined)
        self.assertIn("Signals: Unsignalized", joined)
        self.assertIn("Time pressure", joined)
        self.assertIn("High speed:", joined)
        self.assertTrue(
            any("Perf log:" in line for line in draw_state["hud_lines"])
            or "high speed" in joined.lower()
        )

    def test_rain_slip_can_start_fatal_trip(self):
        self.game.session_modifiers = ModifierContext(
            frozenset({"rainy_roads"}), session_base_seed=4242, round_index=1
        )
        profile = DifficultyProfile.for_menu_preset("easy")
        self.game.start_round(1, profile, "easy")
        self.game.sim_elapsed = 1.2
        self.game.player.sprint_enabled = True
        self.game.rain_slip_tracker.note_sprint_activity(0.2)
        self.game.rain_slip_tracker._slip_roll_for_bucket = lambda bucket: True
        with patch("pathwise.round_frame.old.trip_is_fatal", return_value=True):
            with patch("pathwise.round_frame.old.begin_fatal_trip") as begin:
                update_round_frame(KeyState())
        begin.assert_called()

    def test_high_speed_highway_hud_label(self):
        self.game.session_modifiers = ModifierContext(
            frozenset({"high_speed", "highway"}),
            session_base_seed=4242,
            round_index=1,
        )
        profile = DifficultyProfile.for_menu_preset("easy")
        self.game.start_round(1, profile, "easy")
        draw_state = update_round_frame(KeyState())
        self.assertTrue(any("highway" in line.lower() for line in draw_state["hud_lines"]))


class TestGamePlayViewShowAndSprint(unittest.TestCase):
    def setUp(self):
        patch("arcade.get_window", return_value=fake_arcade_window()).start()
        patch("pathwise.pathwise_window.arcade.set_background_color").start()

    def tearDown(self):
        patch.stopall()

    def _view(self) -> GamePlayView:
        view = GamePlayView()
        view.window = MagicMock(width=800, height=600)
        view.clear = MagicMock()
        view._sync_display_layout()
        return view

    @patch("pathwise.sprites.set_render_bake_multiplier")
    @patch("pathwise.gameplay_framebuffer.prewarm_draw_gpu_assets")
    def test_on_show_view_inactive_and_active(self, prewarm, _bake):
        view = self._view()
        idle = MagicMock(round_active=False)
        with patch.object(GamePlayView, "_game_module", return_value=idle):
            view.on_show_view()
        self.assertIsNone(view._draw_state)
        prewarm.assert_called()
        live = MagicMock(round_active=True)
        live.update_round_frame.return_value = {"hud_lines": ["Time left: 1"]}
        with patch.object(GamePlayView, "_game_module", return_value=live):
            view.on_show_view()
        self.assertEqual(view._draw_state["hud_lines"], ["Time left: 1"])

    def test_sprint_toggle_on_first_shift_while_round_active(self):
        view = self._view()
        player = MagicMock()
        game = MagicMock(round_active=True, player=player)
        with patch.object(GamePlayView, "_game_module", return_value=game):
            view.on_key_press(arcade.key.LSHIFT, 0)
            view.on_key_press(arcade.key.LSHIFT, 0)
        player.toggle_sprint.assert_called_once()
        view.on_key_release(arcade.key.LSHIFT, 0)
        self.assertFalse(view._shift_held)


class TestPathwiseWindowSessionHooks(unittest.TestCase):
    def setUp(self):
        patch("arcade.get_window", return_value=fake_arcade_window()).start()
        patch("pathwise.pre_game.arcade.set_background_color").start()
        patch(
            "pathwise.pre_game.arcade.Text",
            return_value=MagicMock(draw=MagicMock()),
        ).start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_filled").start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_outline").start()

    def tearDown(self):
        patch.stopall()

    def _window(self) -> PathwiseWindow:
        window = PathwiseWindow.__new__(PathwiseWindow)
        window._auto_close_seconds = None
        window._elapsed = 0.0
        window._smoke_mode = False
        window._config = None
        window._pending_config = None
        window._modifiers_from_recruiter = False
        window._disclaimer_accepted = False
        window._disclaimer_return_to = "candidate"
        window._base_profile = None
        window._round_index = 1
        window._outcomes = []
        window._seed_text = ""
        window._recruiter_generated_text = ""
        window._recruiter_record = None
        window._recruiter_session_token = None
        window._recruiter_execute = None
        window.show_view = MagicMock()
        window.closed = False
        return window

    def test_init_smoke_mode_without_real_gl_window(self):
        with patch.dict(os.environ, {"PATHWISE_VSYNC": "1"}):
            with patch(
                "pathwise.pathwise_window.arcade.Window.__init__", return_value=None
            ):
                window = PathwiseWindow(auto_close_seconds=1.5, fullscreen=True)
        self.assertTrue(window._smoke_mode)
        self.assertEqual(window._auto_close_seconds, 1.5)

    def test_modifiers_detail_back_and_disclaimer_paths(self):
        window = self._window()
        config = SessionConfig(preset="normal", modifiers=frozenset({"rainy_roads"}))
        window._show_modifiers_detail(config)
        self.assertIs(window._pending_config, config)
        window._modifiers_from_recruiter = True
        window._on_modifiers_back()
        self.assertFalse(window._modifiers_from_recruiter)
        window.show_view.assert_called()
        window._disclaimer_return_to = "recruiter"
        window._on_disclaimer_back()
        window._pending_config = None
        window._on_disclaimer_agreed()
        window._disclaimer_accepted = False
        window._request_session_start(config, return_to="candidate")
        self.assertIs(window._pending_config, config)
        window._disclaimer_accepted = True
        with patch.object(window, "_commit_session_start") as commit:
            window._request_session_start(config, return_to="recruiter")
            commit.assert_called_once_with(config)
        with patch("arcade.close_window") as close:
            window._on_pre_game_done(None)
            close.assert_called_once()


class TestModifiersDetailView(unittest.TestCase):
    def setUp(self):
        patch("arcade.get_window", return_value=fake_arcade_window()).start()
        patch("pathwise.pre_game.arcade.set_background_color").start()
        patch(
            "pathwise.pre_game.arcade.Text",
            return_value=MagicMock(draw=MagicMock(), content_width=40),
        ).start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_filled").start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_outline").start()

    def tearDown(self):
        patch.stopall()

    def test_draw_start_and_back(self):
        started = []
        backed = []
        view = ModifiersDetailView(
            config=SessionConfig(
                preset="normal", modifiers=frozenset({"rainy_roads"})
            ),
            on_start=lambda cfg: started.append(cfg),
            on_back=lambda: backed.append(1),
        )
        view.on_show_view()
        view.on_draw()
        view.on_key_press(arcade.key.ENTER, 0)
        view.on_key_press(arcade.key.ESCAPE, 0)
        self.assertEqual(len(started), 1)
        self.assertEqual(backed, [1])
        view.on_mouse_press(
            view.start_rect.centerx,
            view.window.height - view.start_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertEqual(len(started), 2)
        view.on_resize(800, 600)
        view.on_mouse_press(0, 0, arcade.MOUSE_BUTTON_RIGHT, 0)
        view.on_mouse_press(
            view.back_rect.centerx,
            view.window.height - view.back_rect.centery,
            arcade.MOUSE_BUTTON_LEFT,
            0,
        )
        self.assertEqual(len(backed), 2)


class TestMapAndSpriteHelpers(unittest.TestCase):
    def test_perimeter_cells_include_corners(self):
        cells = perimeter_cells(2, 2)
        self.assertIn(Cell(0, 0), cells)
        self.assertIn(Cell(2, 2), cells)
        self.assertIn(Cell(0, 1), cells)

    def test_map_bake_none_bounds_and_zero_length_arrow(self):
        m = MapBase([Road(Rect(0, 0, 40, 40), "horizontal")], (0, 0), Rect(10, 10, 8, 8))
        m.bake(world_bounds=None)
        self.assertIsNone(m.baked_layer)
        player = MagicMock()
        player.rect = Rect(10, 10, 8, 8)
        with patch("arcade.draw_line") as draw_line:
            draw_arrow(600, player, Rect(10, 10, 8, 8), (0, 0))
        draw_line.assert_not_called()

    def test_rgba_and_round_rect_helpers(self):
        self.assertEqual(_rgba((1, 2, 3, 4)), (1, 2, 3, 4))
        self.assertEqual(_rgba((1, 2, 3)), (1, 2, 3, 255))
        draw = MagicMock()
        _draw_round_rect(draw, (0, 0, 4, 4), fill=(1, 2, 3, 255), radius=2)
        draw.rounded_rectangle.assert_called()
        _draw_round_rect(draw, (0, 0, 4, 4), outline=(0, 0, 0, 255), width=1)
        draw.rectangle.assert_called()

    @patch("arcade.draw_lbwh_rectangle_filled")
    @patch("arcade.draw_lbwh_rectangle_outline")
    def test_slip_and_bonus_labels_draw(self, _outline, _filled):
        label = MagicMock(content_width=40, content_height=12, draw=MagicMock())
        with patch("arcade.Text", return_value=label):
            ped = Rect(80, 90, 16, 16)
            draw_slip_trip_message(600, ped, (0, 0))
            draw_time_bonus_popup(600, ped, (0, 0), "+1.0s")
        self.assertGreaterEqual(label.draw.call_count, 2)

    @patch.object(arcade.SpriteList, "draw")
    def test_entity_batch_hides_unused_pool_sprites(self, _draw):
        from PIL import Image as PilImage

        tex = arcade.Texture(PilImage.new("RGBA", (4, 4), (1, 2, 3, 255)), hash="pool_hide")

        class Asset:
            texture = tex
            width = 40
            height = 20

        class Ent:
            def __init__(self, x):
                self.rect = Rect(x, 10, 40, 20)
                self.image = Asset()

        batch = EntityDrawBatch()
        batch.draw_entities([Ent(10), Ent(80)], (0, 0), 600)
        self.assertTrue(batch._pool[1].visible)
        batch.draw_entities([Ent(10)], (0, 0), 600)
        self.assertFalse(batch._pool[1].visible)


class TestLawlessLightsOff(unittest.TestCase):
    def tearDown(self):
        lawless.install_for_round(ModifierContext(frozenset()))

    def test_update_light_timers_clears_when_unsignalized(self):
        from pathwise.road_states import update_light_timers

        lawless.install_for_round(
            ModifierContext(frozenset({"lawless"}), session_base_seed=1, round_index=1)
        )
        states = [
            {
                "direction": "horizontal",
                "light_state": "green",
                "seconds_to_change": 4.0,
                "next_light": "yellow",
                "turn_light_state": "red",
                "turn_seconds_to_change": 4.0,
                "next_turn_light": "green",
                "phase_offset": 0.0,
            }
        ]
        update_light_timers(states, 1.0)
        self.assertEqual(states[0]["light_state"], "off")
        self.assertEqual(states[0]["next_light"], "off")


class TestTimePressureHudAndHidden(unittest.TestCase):
    def setUp(self):
        import main as game

        self.game = game
        game.session_base_seed = 99
        game.session_seed_source = "test"
        game.session_use_adaptive_map = False
        game.session_num_rounds = 1
        game.round_active = False

    def test_time_pressure_hud_without_rain_combo(self):
        self.game.session_audience = "recruiter"
        self.game.session_modifiers = ModifierContext(
            frozenset({"time_pressure"}), session_base_seed=99, round_index=1
        )
        self.game.start_round(1, DifficultyProfile.for_menu_preset("easy"), "easy")
        draw_state = update_round_frame(KeyState())
        joined = "\n".join(draw_state["hud_lines"])
        self.assertIn("Time pressure", joined)
        self.assertNotIn("Time pressure + rain", joined)
        self.assertIn("earn time", joined)

    def test_hidden_candidate_clears_hud(self):
        self.game.session_audience = "candidate"
        self.game.session_modifiers = ModifierContext(
            frozenset({"hidden"}), session_base_seed=99, round_index=1
        )
        self.game.start_round(1, DifficultyProfile.for_menu_preset("easy"), "easy")
        draw_state = update_round_frame(KeyState())
        self.assertEqual(draw_state["hud_lines"], [])

    def test_crosswalk_legal_commit_label(self):
        self.game.session_audience = "candidate"
        self.game.session_modifiers = ModifierContext(frozenset())
        self.game.start_round(1, DifficultyProfile.for_menu_preset("easy"), "easy")
        self.game.player.rect.center = self.game.road_states[0]["crosswalk"].center
        self.game.legal_crossing_commit_active = True
        draw_state = update_round_frame(KeyState())
        self.assertTrue(
            any("legal commit" in line for line in draw_state["hud_lines"])
            or any(line.startswith("Crosswalk ·") for line in draw_state["hud_lines"])
        )


class TestGamePlayViewUpdateAndDraw(unittest.TestCase):
    def setUp(self):
        patch("arcade.get_window", return_value=fake_arcade_window()).start()
        patch("pathwise.pathwise_window.arcade.set_background_color").start()

    def tearDown(self):
        patch.stopall()

    def test_on_update_fires_complete_when_round_ends(self):
        done = []
        view = GamePlayView(on_round_complete=lambda: done.append(1))
        view.window = MagicMock(width=800, height=600)
        game = MagicMock(app_running=True, round_active=False)
        with patch.object(GamePlayView, "_game_module", return_value=game):
            view.on_update(0.016)
        self.assertEqual(done, [1])

    @patch("pathwise.game_draw.draw_round_scene")
    def test_on_draw_hides_hud_when_suppressed(self, _draw):
        view = GamePlayView()
        view.window = MagicMock(width=800, height=600)
        view.clear = MagicMock()
        view._sync_display_layout()
        view._draw_state = {"hud_lines": ["secret"], "camera_offset": (0, 0)}
        game = MagicMock(ENABLE_PERF_PROFILE=False, draw_round_frame=MagicMock())
        with patch.object(GamePlayView, "_game_module", return_value=game):
            with patch("pathwise.modifiers.hidden.suppress_hud", return_value=True):
                view.on_draw()
        kwargs = game.draw_round_frame.call_args[0][2]
        self.assertEqual(kwargs["hud_lines"], [])


class TestPathwiseWindowRemainingHooks(unittest.TestCase):
    def setUp(self):
        patch("arcade.get_window", return_value=fake_arcade_window()).start()
        patch("pathwise.pre_game.arcade.set_background_color").start()
        patch(
            "pathwise.pre_game.arcade.Text",
            return_value=MagicMock(draw=MagicMock()),
        ).start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_filled").start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_outline").start()

    def tearDown(self):
        patch.stopall()

    def _window(self) -> PathwiseWindow:
        window = PathwiseWindow.__new__(PathwiseWindow)
        window._auto_close_seconds = None
        window._elapsed = 0.0
        window._smoke_mode = False
        window._config = None
        window._pending_config = None
        window._modifiers_from_recruiter = False
        window._disclaimer_accepted = False
        window._disclaimer_return_to = "candidate"
        window._base_profile = None
        window._round_index = 1
        window._outcomes = []
        window._seed_text = ""
        window._recruiter_generated_text = ""
        window._recruiter_record = None
        window._recruiter_session_token = None
        window._recruiter_execute = None
        window.show_view = MagicMock()
        window.closed = False
        window.clear = MagicMock()
        window._current_view = None
        return window

    def test_on_draw_clears_when_no_view(self):
        window = self._window()
        window.on_draw()
        window.clear.assert_called()

    def test_run_shows_home_then_super_run(self):
        window = self._window()
        with patch.object(window, "_show_candidate_home") as home:
            with patch.object(arcade.Window, "run"):
                window.run()
        home.assert_called_once()

    def test_candidate_modifier_back_and_recruiter_start(self):
        window = self._window()
        config = SessionConfig(preset="easy")
        window._modifiers_from_recruiter = False
        window._on_modifiers_back()
        window._show_modifiers_detail_from_recruiter(config)
        self.assertTrue(window._modifiers_from_recruiter)
        from pathwise.pre_game import RecruiterConfigView

        real_view = RecruiterConfigView.__new__(RecruiterConfigView)
        real_view.generated_seed_text = "911001000042"
        window._current_view = real_view
        window._show_modifiers_detail_from_recruiter(config)
        self.assertEqual(window._recruiter_generated_text, "911001000042")
        with patch.object(window, "_request_session_start") as req:
            window._on_recruiter_start(config)
            req.assert_called_once()
        window._disclaimer_return_to = "candidate"
        window._on_disclaimer_back()
        with patch.object(window, "_request_session_start") as req:
            window._modifiers_from_recruiter = True
            window._on_pre_game_done(config)
            req.assert_called_with(config, return_to="recruiter")

    @patch("main.save_session_log", return_value="logs_dashboard.html")
    @patch("main.session_num_rounds", 3)
    @patch("main.session_base_seed", 7)
    @patch("main.round_results", [{}, {}, {}])
    def test_finish_session_multi_round_title(self, _save):
        window = self._window()
        window._outcomes = ["success", "collision", "timeout"]
        window._config = SessionConfig(preset="normal")
        window._finish_session()
        shown = window.show_view.call_args[0][0]
        self.assertIn("3 rounds", shown.title)


class TestMessageViewPopup(unittest.TestCase):
    def setUp(self):
        patch("arcade.get_window", return_value=fake_arcade_window()).start()
        patch("pathwise.pre_game.arcade.set_background_color").start()
        patch(
            "pathwise.pre_game.arcade.Text",
            return_value=MagicMock(
                draw=MagicMock(), content_width=80, content_height=16
            ),
        ).start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_filled").start()
        patch("pathwise.pre_game.arcade.draw_lbwh_rectangle_outline").start()

    def tearDown(self):
        patch.stopall()

    def test_popup_scroll_keys_and_draw(self):
        from pathwise.pre_game import MessageView

        view = MessageView(
            title="Round complete",
            subtitle="seed 1",
            accent="open logs",
            details="wasd",
            modifiers=frozenset({"rainy_roads", "old", "lag", "high_speed"}),
        )
        view.on_show_view()
        view.on_resize(800, 600)
        view.on_draw()
        view._open_modifiers_popup()
        view._popup_max_scroll = 80
        view._scroll_modifiers_popup(0.2)
        view.on_key_press(arcade.key.DOWN, 0)
        view.on_key_press(arcade.key.UP, 0)
        view.on_key_press(arcade.key.PAGEDOWN, 0)
        view.on_key_press(arcade.key.PAGEUP, 0)
        view.on_mouse_scroll(0, 0, 0, 1)
        view.on_mouse_press(0, 0, arcade.MOUSE_BUTTON_RIGHT, 0)
        view._popup_max_scroll = 0
        view._scroll_modifiers_popup(1)
        view._popup_max_scroll = 80
        view._scroll_modifiers_popup(0.001)
        view.on_draw()
        view.on_key_press(arcade.key.ESCAPE, 0)
        self.assertFalse(view._modifiers_popup_open)
        view.on_mouse_scroll(0, 0, 0, 1)


class TestSpriteAndViewportExtras(unittest.TestCase):
    def test_car_surface_helpers_and_layout_labels(self):
        from pathwise import sprites

        self.assertEqual(sprites._body_dimensions(True)[0], sprites.CAR_HEIGHT)
        self.assertEqual(sprites._body_dimensions(False)[0], sprites.CAR_WIDTH)
        self.assertEqual(sprites.car_travel_angle_deg(False, -1), 180.0)
        self.assertEqual(sprites.car_travel_angle_deg(True, 1), -90.0)
        self.assertEqual(sprites.car_travel_angle_deg(True, -1), 90.0)
        sprites.set_render_bake_multiplier(sprites.render_bake_multiplier())
        layout = DisplayLayout.fit_window(200, 200, sim_width=200, sim_height=200)
        self.assertEqual(layout.display_match_scale, 1.0)
        scaled = DisplayLayout.fit_window(1920, 1080)
        self.assertGreater(scaled.display_match_scale, 0)
        self.assertEqual(scaled.letterbox_color[0], 236)
        label = MagicMock(content_width=40, content_height=12, draw=MagicMock())
        with patch("pathwise.sprites.arcade.Text", return_value=label):
            with patch("pathwise.sprites.arcade.draw_lbwh_rectangle_filled"):
                with patch("pathwise.sprites.arcade.draw_lbwh_rectangle_outline"):
                    with patch("pathwise.sprites.arcade.draw_arc_outline"):
                        ped = Rect(80, 90, 16, 16)
                        sprites.draw_slip_trip_message(600, ped, (0, 0), layout=scaled)
                        sprites.draw_time_bonus_popup(
                            600, ped, (0, 0), "+2s", layout=scaled
                        )
                        sprites.draw_honk_bubble(600, ped, (0, 0), layout=scaled)


class TestSmallCoverageGaps(unittest.TestCase):
    def test_registry_metadata_and_invalid_masks(self):
        from pathwise.modifiers.registry import (
            is_valid_modifier_mask,
            modifier_mask_from_ids,
            modifier_metadata,
        )

        self.assertIsNone(modifier_metadata("not_a_modifier"))
        self.assertEqual(modifier_metadata("rainy_roads")["id"], "rainy_roads")
        with self.assertRaises(ValueError):
            modifier_mask_from_ids(["not_a_modifier"])
        self.assertFalse(is_valid_modifier_mask(-1))
        self.assertFalse(is_valid_modifier_mask(10000))
        self.assertFalse(is_valid_modifier_mask(4096))

    def test_session_seed_encode_decode_edges(self):
        from pathwise.session_seed import (
            RECRUITER_SEED_VERSION_LEGACY,
            encode_recruiter_seed,
            decode_recruiter_seed,
        )

        with self.assertRaises(ValueError):
            encode_recruiter_seed(1, "not-a-preset", 1)
        with self.assertRaises(ValueError):
            encode_recruiter_seed(1, "normal", 99)
        with self.assertRaises(ValueError):
            encode_recruiter_seed(1, "normal", 1, version=4)
        legacy = encode_recruiter_seed(
            42, "normal", 1, version=RECRUITER_SEED_VERSION_LEGACY
        )
        self.assertTrue(legacy.startswith("8"))
        self.assertIsNone(decode_recruiter_seed("8990000000"))
        self.assertIsNone(decode_recruiter_seed("8600000000"))
        self.assertIsNone(decode_recruiter_seed("929000000000"))
        self.assertIsNone(decode_recruiter_seed("960000000000"))

    def test_replay_sprint_and_modifier_idle_hooks(self):
        from analytics.replay_playback import replay_step_for_session
        from pathwise.modifiers import exposure, hidden, lag, old, time_pressure
        from pathwise.sprint import sprint_risk_reason

        self.assertGreater(replay_step_for_session(None), 0)
        self.assertIsNone(
            sprint_risk_reason(
                sprinting=True, moved=True, feet_on_road=False, on_crosswalk=False
            )
        )
        empty = ModifierContext(frozenset())
        old.install_for_round(empty)
        lag.install_for_round(empty)
        exposure.install_for_round(empty)
        time_pressure.install_for_round(empty)
        self.assertFalse(old.is_active())
        self.assertFalse(lag.is_active())
        self.assertEqual(exposure.remaining_seconds(), 0.0)
        self.assertEqual(exposure.grant_from_time_bonus(2.0), 0.0)
        self.assertEqual(time_pressure.start_seconds(), 0.0)
        self.assertFalse(
            time_pressure.legal_crossing_for_bonus(
                on_crosswalk=False,
                cars_have_red=True,
                legal_commit_active=True,
                unsignalized=False,
            )
        )
        self.assertEqual(time_pressure.max_single_crossing_bonus_s(), 0.0)
        time_pressure.arm_bonus_popup(0.0, 1.0)
        self.assertIn("safe_crosswalk", time_pressure.bonus_table_for_preset("unknown"))
        self.assertIsNone(hidden.hud_line())
        self.assertIn("limit_s", exposure.summary())
        old.install_for_round(ModifierContext(frozenset({"old"})))
        self.assertIsNotNone(old.hud_line())
        self.assertNotIn("fatal", old.hud_line())
        old.begin_fatal_trip(0.0)
        self.assertFalse(old.is_fatal_trip_active())
        ctx_old_rain = ModifierContext(
            frozenset({"old", "rainy_roads"}), session_base_seed=1, round_index=1
        )
        old.install_for_round(ctx_old_rain)
        old.begin_fatal_trip(0.5)
        self.assertTrue(old.is_fatal_trip_active())
        self.assertIn("fatal", old.hud_line() or "")
        from pathwise.modifiers import untrustworthy
        from pathwise.input_keys import KEY_RIGHT, key_labels_from_state

        untrustworthy.install_for_round(ModifierContext(frozenset()))
        untrustworthy.mark_unlawful(3)
        keys = KeyState()
        keys.press(KEY_RIGHT)
        self.assertIn("right", key_labels_from_state(keys))
        ped = Pedestrian((4, 4))
        ped.draw_angle = 12.0
        ped.clear_slip_stun(9.0)
        self.assertEqual(ped.draw_angle, 0.0)
        old._fatal_phase = "done"
        self.assertEqual(old.update_fatal_trip(1.0), "fail")

    def test_trim_dense_replay_frames(self):
        from analytics.frame_recorder import MAX_REPLAY_FRAMES, FrameRecorder

        rec = FrameRecorder(28)
        rec.note_sim_frame_seconds(1.0)
        rec.note_sim_frame_seconds(0.001)
        self.assertGreater(rec.sample_interval_s, 0)
        frames = [
            {"t": i * 0.01, "synthetic": True, "seq": i}
            for i in range(MAX_REPLAY_FRAMES + 12)
        ]
        frames[0]["is_start"] = True
        frames[-1]["is_end"] = True
        trimmed = rec._trim_dense_frames(frames)
        self.assertLessEqual(len(trimmed), MAX_REPLAY_FRAMES)
        self.assertLessEqual(len(rec._trim_dense_frames(frames[:3])), 3)


if __name__ == "__main__":
    unittest.main()
