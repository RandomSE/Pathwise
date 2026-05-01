import pygame
import random
import json
import time
import commonUtils
import map

# --- Config ---
utils = commonUtils
WIDTH, HEIGHT = utils.WIDTH, utils.HEIGHT
ROAD_Y = utils.ROAD_Y
ROAD_HEIGHT = utils.ROAD_HEIGHT
CAR_WIDTH, CAR_HEIGHT = utils.CAR_WIDTH, utils.CAR_HEIGHT
PEDESTRIAN_SIZE = utils.PEDESTRIAN_SIZE
PEDESTRIAN_SPEED = utils.PEDESTRIAN_SPEED
CAR_SPEED = utils.CAR_SPEED
ROUND_TIME_LIMIT = 75
HUD_TEXT_COLOR = (20, 20, 20)
RISK_COOLDOWN_SECONDS = 1.5
LIGHT_GREEN_DURATION = 10.0
LIGHT_YELLOW_DURATION = 2.5
LIGHT_RED_DURATION = 7.0
STOP_LINE_GAP = 6
CAR_SPAWN_CLEARANCE = 20
CROSSWALK_THICKNESS = 14
INTERSECTION_GAP_MIN = 6
NEAR_MISS_DISTANCE = 56
TOO_CLOSE_DISTANCE = 82
PLAYER_AVOIDANCE_CHANCE = 0.8

# --- Init ---
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Pathwise MVP")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 28)
sign_font = pygame.font.SysFont(None, 16)

# --- Entities --- 
class Car(pygame.sprite.Sprite):
    def __init__(self, x, y, speed, vertical=False):
        super().__init__()
        if (vertical):
            self.image = pygame.Surface((CAR_HEIGHT, CAR_WIDTH))  # swap dimensions for vertical cars
        else: 
            self.image = pygame.Surface((CAR_WIDTH, CAR_HEIGHT))
        self.image.fill((200, 0, 0))
        self.rect = self.image.get_rect(topleft=(x, y))
        self.base_speed = abs(speed)
        self.direction = 1 if speed >= 0 else -1
        self.current_speed = float(self.base_speed)
        self.acceleration = 0.16
        self.brake_strength = 0.42
        self.speed = speed
        self.vertical = vertical

    def _distance_to_other(self, other):
        if self.vertical:
            ahead = (other.rect.centery - self.rect.centery) * self.direction
            lane_gap = abs(other.rect.centerx - self.rect.centerx)
        else:
            ahead = (other.rect.centerx - self.rect.centerx) * self.direction
            lane_gap = abs(other.rect.centery - self.rect.centery)
        return ahead, lane_gap

    def _distance_to_intersection_entry(self, zone):
        if self.vertical:
            if self.direction > 0:
                return zone.top - self.rect.bottom
            return self.rect.top - zone.bottom
        if self.direction > 0:
            return zone.left - self.rect.right
        return self.rect.left - zone.right

    def _clamp_before_intersection(self, zone):
        if self.vertical:
            if self.direction > 0:
                self.rect.bottom = zone.top - STOP_LINE_GAP
            else:
                self.rect.top = zone.bottom + STOP_LINE_GAP
        else:
            if self.direction > 0:
                self.rect.right = zone.left - STOP_LINE_GAP
            else:
                self.rect.left = zone.right + STOP_LINE_GAP

    def update(self, all_cars, road_states, world_rect, intersection_zones, player_rect):
        desired_speed = self.base_speed
        blocking_controls = []
        will_yield_to_player = random.random() < PLAYER_AVOIDANCE_CHANCE

        for state in road_states:
            if state["direction"] != ("horizontal" if self.vertical else "vertical"):
                continue
            if not self.rect.colliderect(state["road_rect"].inflate(180, 180)):
                continue

            if self.vertical:
                stop_distance = (state["stop_axis"] - self.rect.centery) * self.direction
                in_crossing_lane = abs(self.rect.centerx - state["crosswalk"].centerx) < 50
            else:
                stop_distance = (state["stop_axis"] - self.rect.centerx) * self.direction
                in_crossing_lane = abs(self.rect.centery - state["crosswalk"].centery) < 50

            if in_crossing_lane:
                if state["light_state"] == "red" and 0 < stop_distance < 210:
                    desired_speed = 0
                    blocking_controls.append(state)
                elif state["light_state"] == "yellow" and 0 < stop_distance < 170:
                    if stop_distance < 95:
                        desired_speed = 0
                    else:
                        desired_speed = min(desired_speed, self.base_speed * 0.45)
                elif state["player_waiting"] and 0 < stop_distance < 210 and random.random() < 0.72:
                    desired_speed = min(desired_speed, self.base_speed * 0.33)

                if state["stop_active"] and 0 < stop_distance < 100:
                    desired_speed = min(desired_speed, self.base_speed * 0.2)

        # Strong player-avoidance behavior: brake early when player is in/near lane ahead.
        if self.vertical:
            player_ahead = (player_rect.centery - self.rect.centery) * self.direction
            player_lane_gap = abs(player_rect.centerx - self.rect.centerx)
        else:
            player_ahead = (player_rect.centerx - self.rect.centerx) * self.direction
            player_lane_gap = abs(player_rect.centery - self.rect.centery)

        if 0 < player_ahead < 300 and player_lane_gap < 70:
            if will_yield_to_player:
                if player_ahead < 90:
                    desired_speed = 0
                elif player_ahead < 150:
                    desired_speed = min(desired_speed, self.base_speed * 0.18)
                else:
                    desired_speed = min(desired_speed, self.base_speed * 0.4)
            else:
                # Imperfect driver behavior: sometimes late response.
                desired_speed = min(desired_speed, self.base_speed * 0.72)

        # If player's body intersects the immediate travel corridor, force full stop.
        lookahead_rect = self.rect.copy()
        if self.vertical:
            lookahead_rect.height += int(max(40, self.current_speed * 10))
            if self.direction < 0:
                lookahead_rect.y -= int(max(40, self.current_speed * 10))
        else:
            lookahead_rect.width += int(max(40, self.current_speed * 10))
            if self.direction < 0:
                lookahead_rect.x -= int(max(40, self.current_speed * 10))
        if lookahead_rect.colliderect(player_rect):
            if will_yield_to_player:
                desired_speed = 0
            else:
                desired_speed = min(desired_speed, self.base_speed * 0.65)

        for zone in intersection_zones:
            distance_to_entry = self._distance_to_intersection_entry(zone)
            if distance_to_entry < -10 or distance_to_entry > 180:
                continue

            zone_occupied = any(other != self and other.rect.colliderect(zone.inflate(6, 6)) for other in all_cars)
            if zone_occupied:
                if distance_to_entry < 90:
                    desired_speed = 0
                else:
                    desired_speed = min(desired_speed, self.base_speed * 0.3)

        for other in all_cars:
            if other == self or other.vertical != self.vertical or other.direction != self.direction:
                continue
            ahead, lane_gap = self._distance_to_other(other)
            if 0 < ahead < 170 and lane_gap < 35:
                if ahead < 65:
                    desired_speed = 0
                else:
                    desired_speed = min(desired_speed, other.current_speed * 0.88)

        if self.current_speed < desired_speed:
            self.current_speed = min(desired_speed, self.current_speed + self.acceleration)
        else:
            self.current_speed = max(desired_speed, self.current_speed - self.brake_strength)

        signed_speed = self.current_speed * self.direction

        keep_clear_zones = intersection_zones + [state["crosswalk"] for state in road_states]
        in_keep_clear_zone = any(self.rect.colliderect(zone) for zone in keep_clear_zones)
        if in_keep_clear_zone and abs(signed_speed) < 0.01:
            crawl_speed = 1.1 * self.direction
            crawl_rect = self.rect.copy()
            if self.vertical:
                crawl_rect.y += crawl_speed
            else:
                crawl_rect.x += crawl_speed

            imminent_stop_required = crawl_rect.colliderect(player_rect)
            if not imminent_stop_required:
                for other in all_cars:
                    if other == self:
                        continue
                    if crawl_rect.colliderect(other.rect):
                        imminent_stop_required = True
                        break

            if not imminent_stop_required:
                self.current_speed = max(self.current_speed, 1.1)
                signed_speed = self.current_speed * self.direction

        blocked_by_line = False
        if signed_speed != 0:
            for state in blocking_controls:
                stop_axis = state["stop_axis"]
                if self.vertical:
                    if self.direction > 0 and self.rect.bottom + signed_speed >= stop_axis - STOP_LINE_GAP:
                        self.rect.bottom = stop_axis - STOP_LINE_GAP
                        blocked_by_line = True
                    elif self.direction < 0 and self.rect.top + signed_speed <= stop_axis + STOP_LINE_GAP:
                        self.rect.top = stop_axis + STOP_LINE_GAP
                        blocked_by_line = True
                else:
                    if self.direction > 0 and self.rect.right + signed_speed >= stop_axis - STOP_LINE_GAP:
                        self.rect.right = stop_axis - STOP_LINE_GAP
                        blocked_by_line = True
                    elif self.direction < 0 and self.rect.left + signed_speed <= stop_axis + STOP_LINE_GAP:
                        self.rect.left = stop_axis + STOP_LINE_GAP
                        blocked_by_line = True
                if blocked_by_line:
                    break

        if blocked_by_line:
            self.current_speed = 0
            self.speed = 0
        else:
            blocked_by_intersection = False
            for zone in intersection_zones:
                distance_to_entry = self._distance_to_intersection_entry(zone)
                if distance_to_entry < -10 or distance_to_entry > 180:
                    continue
                zone_occupied = any(other != self and other.rect.colliderect(zone.inflate(6, 6)) for other in all_cars)
                if not zone_occupied:
                    continue

                will_enter_zone = False
                if self.vertical:
                    if self.direction > 0:
                        will_enter_zone = self.rect.bottom + signed_speed >= zone.top - STOP_LINE_GAP
                    else:
                        will_enter_zone = self.rect.top + signed_speed <= zone.bottom + STOP_LINE_GAP
                else:
                    if self.direction > 0:
                        will_enter_zone = self.rect.right + signed_speed >= zone.left - STOP_LINE_GAP
                    else:
                        will_enter_zone = self.rect.left + signed_speed <= zone.right + STOP_LINE_GAP

                if will_enter_zone:
                    self._clamp_before_intersection(zone)
                    self.current_speed = 0
                    self.speed = 0
                    blocked_by_intersection = True
                    break

            if blocked_by_intersection:
                pass
            else:
                next_rect = self.rect.copy()
                if self.vertical:
                    next_rect.y += signed_speed
                else:
                    next_rect.x += signed_speed

                imminent_collision = False
                for other in all_cars:
                    if other == self:
                        continue
                    if next_rect.colliderect(other.rect):
                        imminent_collision = True
                        break

                if imminent_collision:
                    self.current_speed = 0
                    self.speed = 0
                else:
                    self.speed = signed_speed
                    self.rect = next_rect

        self.rect.clamp_ip(world_rect.inflate(300, 300))
        if self.rect.right < 0 or self.rect.left > WIDTH * 2: # allow offscreen cleanup 
            self.kill() 

class Pedestrian(pygame.sprite.Sprite): 
    def __init__(self, start_pos): 
        super().__init__() 
        self.image = pygame.Surface((PEDESTRIAN_SIZE, PEDESTRIAN_SIZE)) 
        self.image.fill((0, 200, 0)) 
        self.rect = self.image.get_rect(center=start_pos) 
    def update(self, keys): 
        if keys[pygame.K_LEFT]: 
            self.rect.x -= PEDESTRIAN_SPEED 
        if keys[pygame.K_RIGHT]: 
            self.rect.x += PEDESTRIAN_SPEED 
        if keys[pygame.K_UP]: 
            self.rect.y -= PEDESTRIAN_SPEED 
        if keys[pygame.K_DOWN]: 
            self.rect.y += PEDESTRIAN_SPEED


# --- Setup --- 
map_classes = [map.VerticalMap, map.HorizontalMap, map.MixedMap]
current_map = random.choice(map_classes)() 
cars = pygame.sprite.Group() 
player = Pedestrian(current_map.start_pos) 
all_sprites = pygame.sprite.Group(player) 
start_time = time.time() 
crossings = 0 
collisions = 0 
risk_events = 0
last_risk_time = 0
failure_reason = "none"
running = True


def build_world_bounds(roads, start_pos, goal_rect):
    min_left = min([r.rect.left for r in roads] + [start_pos[0] - 80, goal_rect.left]) - 120
    max_right = max([r.rect.right for r in roads] + [start_pos[0] + 80, goal_rect.right]) + 120
    min_top = min([r.rect.top for r in roads] + [start_pos[1] - 80, goal_rect.top]) - 120
    max_bottom = max([r.rect.bottom for r in roads] + [start_pos[1] + 80, goal_rect.bottom]) + 120
    return pygame.Rect(min_left, min_top, max_right - min_left, max_bottom - min_top)


def build_road_states(roads):
    def add_state(collector, road, direction, crosswalk, sign_rect, phase_offset):
        collector.append(
            {
                "road_rect": road.rect,
                "direction": direction,
                "crosswalk": crosswalk,
                "stop_axis": crosswalk.centerx if direction == "vertical" else crosswalk.centery,
                "sign_rect": sign_rect,
                "phase_offset": phase_offset,
                "light_state": "green",
                "player_waiting": False,
                "stop_active": True,
            }
        )

    road_states = []
    cycle = LIGHT_GREEN_DURATION + LIGHT_YELLOW_DURATION + LIGHT_RED_DURATION
    vertical_roads = [r for r in roads if r.direction == "vertical"]
    horizontal_roads = [r for r in roads if r.direction == "horizontal"]
    intersection_by_road = {id(road): [] for road in roads}

    for v_road in vertical_roads:
        for h_road in horizontal_roads:
            intersection_rect = v_road.rect.clip(h_road.rect)
            if intersection_rect.width <= 0 or intersection_rect.height <= 0:
                continue
            intersection_by_road[id(v_road)].append(intersection_rect)
            intersection_by_road[id(h_road)].append(intersection_rect)

            base_offset = ((intersection_rect.centerx + intersection_rect.centery) % 31) / 31.0 * cycle

            # Crossing across the horizontal road (left and right approaches).
            left_space = intersection_rect.left - v_road.rect.left
            right_space = v_road.rect.right - intersection_rect.right
            left_thickness = min(CROSSWALK_THICKNESS, max(0, left_space - INTERSECTION_GAP_MIN - 2))
            right_thickness = min(CROSSWALK_THICKNESS, max(0, right_space - INTERSECTION_GAP_MIN - 2))
            if left_thickness >= 4:
                left_x = intersection_rect.left - INTERSECTION_GAP_MIN - left_thickness
                left_crosswalk = pygame.Rect(left_x, v_road.rect.top, left_thickness, v_road.rect.height)
                add_state(
                    road_states,
                    v_road,
                    "vertical",
                    left_crosswalk,
                    pygame.Rect(left_crosswalk.left - 28, left_crosswalk.top - 26, 18, 18),
                    base_offset,
                )
            if right_thickness >= 4:
                right_x = intersection_rect.right + INTERSECTION_GAP_MIN
                right_crosswalk = pygame.Rect(right_x, v_road.rect.top, right_thickness, v_road.rect.height)
                add_state(
                    road_states,
                    v_road,
                    "vertical",
                    right_crosswalk,
                    pygame.Rect(right_crosswalk.right + 10, right_crosswalk.top - 26, 18, 18),
                    base_offset + 1.3,
                )

            # Crossing across the vertical road (top and bottom approaches).
            top_space = intersection_rect.top - h_road.rect.top
            bottom_space = h_road.rect.bottom - intersection_rect.bottom
            top_thickness = min(CROSSWALK_THICKNESS, max(0, top_space - INTERSECTION_GAP_MIN - 2))
            bottom_thickness = min(CROSSWALK_THICKNESS, max(0, bottom_space - INTERSECTION_GAP_MIN - 2))
            if top_thickness >= 4:
                top_y = intersection_rect.top - INTERSECTION_GAP_MIN - top_thickness
                top_crosswalk = pygame.Rect(h_road.rect.left, top_y, h_road.rect.width, top_thickness)
                add_state(
                    road_states,
                    h_road,
                    "horizontal",
                    top_crosswalk,
                    pygame.Rect(top_crosswalk.left - 26, top_crosswalk.top - 26, 18, 18),
                    base_offset + (LIGHT_GREEN_DURATION / 2.0),
                )
            if bottom_thickness >= 4:
                bottom_y = intersection_rect.bottom + INTERSECTION_GAP_MIN
                bottom_crosswalk = pygame.Rect(h_road.rect.left, bottom_y, h_road.rect.width, bottom_thickness)
                add_state(
                    road_states,
                    h_road,
                    "horizontal",
                    bottom_crosswalk,
                    pygame.Rect(bottom_crosswalk.left - 26, bottom_crosswalk.bottom + 10, 18, 18),
                    base_offset + (LIGHT_GREEN_DURATION / 2.0) + 1.3,
                )

    # Roads without intersections get one center crossing.
    for idx, road in enumerate(roads):
        if intersection_by_road[id(road)]:
            continue
        phase_offset = (idx * 3.7) % cycle
        if road.direction == "vertical":
            crosswalk = pygame.Rect(road.rect.centerx - CROSSWALK_THICKNESS // 2, road.rect.top, CROSSWALK_THICKNESS, road.rect.height)
            sign_rect = pygame.Rect(crosswalk.left - 28, crosswalk.top - 26, 18, 18)
        else:
            crosswalk = pygame.Rect(road.rect.left, road.rect.centery - CROSSWALK_THICKNESS // 2, road.rect.width, CROSSWALK_THICKNESS)
            sign_rect = pygame.Rect(crosswalk.left - 26, crosswalk.top - 26, 18, 18)
        add_state(road_states, road, road.direction, crosswalk, sign_rect, phase_offset)

    return road_states


def build_intersection_zones(roads):
    zones = []
    vertical_roads = [r for r in roads if r.direction == "vertical"]
    horizontal_roads = [r for r in roads if r.direction == "horizontal"]
    for v_road in vertical_roads:
        for h_road in horizontal_roads:
            zone = v_road.rect.clip(h_road.rect)
            if zone.width > 0 and zone.height > 0:
                zones.append(zone)
    return zones


def lane_center_for_road(road, direction, vertical):
    if vertical:
        lane_half = road.rect.width * 0.25
        # Left-side traffic: down-going cars keep right side of screen; up-going keep left.
        return int(road.rect.centerx + lane_half if direction > 0 else road.rect.centerx - lane_half)
    lane_half = road.rect.height * 0.25
    # Left-side traffic: right-going uses upper lane; left-going uses lower lane.
    return int(road.rect.centery - lane_half if direction > 0 else road.rect.centery + lane_half)


def get_light_state(elapsed_seconds):
    cycle_length = LIGHT_GREEN_DURATION + LIGHT_YELLOW_DURATION + LIGHT_RED_DURATION
    t = elapsed_seconds % cycle_length
    if t < LIGHT_GREEN_DURATION:
        return "green"
    if t < LIGHT_GREEN_DURATION + LIGHT_YELLOW_DURATION:
        return "yellow"
    return "red"


def try_spawn_car(road, cars_group, player_sprite, all_sprites_group):
    if road.direction == "vertical":
        side = random.choice(["left", "right"])
        speed = CAR_SPEED if side == "left" else -CAR_SPEED
        y = lane_center_for_road(road, 1 if speed > 0 else -1, vertical=False) - (CAR_HEIGHT // 2)
        x = road.rect.left - CAR_WIDTH - CAR_SPAWN_CLEARANCE if side == "left" else road.rect.right + CAR_SPAWN_CLEARANCE
        candidate = Car(x, y, speed)
    else:
        side = random.choice(["top", "bottom"])
        speed = CAR_SPEED if side == "top" else -CAR_SPEED
        x = lane_center_for_road(road, 1 if speed > 0 else -1, vertical=True) - (CAR_HEIGHT // 2)
        y = road.rect.top - CAR_HEIGHT - CAR_SPAWN_CLEARANCE if side == "top" else road.rect.bottom + CAR_SPAWN_CLEARANCE
        candidate = Car(x, y, speed, vertical=True)

    for other in cars_group:
        if candidate.rect.colliderect(other.rect.inflate(8, 8)):
            return
    if candidate.rect.colliderect(player_sprite.rect.inflate(120, 120)):
        return

    cars_group.add(candidate)
    all_sprites_group.add(candidate)


world_bounds = build_world_bounds(current_map.roads, current_map.start_pos, current_map.goal_rect)
road_states = build_road_states(current_map.roads)
intersection_zones = build_intersection_zones(current_map.roads)
wall_rects = [
    pygame.Rect(world_bounds.left - 4000, world_bounds.top - 4000, 4000, world_bounds.height + 8000),
    pygame.Rect(world_bounds.right, world_bounds.top - 4000, 4000, world_bounds.height + 8000),
    pygame.Rect(world_bounds.left, world_bounds.top - 4000, world_bounds.width, 4000),
    pygame.Rect(world_bounds.left, world_bounds.bottom, world_bounds.width, 4000),
]

def end_game(collided, timed_out=False): 
    global crossings, collisions, running, risk_events, failure_reason
    end_time = time.time() 
    duration = round(end_time - start_time, 2) 
    if collided: 
        collisions += 1 
        failure_reason = "collision"
    elif timed_out:
        failure_reason = "timeout"
    else:
        failure_reason = "goal_reached"
    log = { 
        "time": duration, 
        "crossings": crossings, 
        "collisions": collisions, 
        "risks_taken": risk_events,
        "failure_reason": failure_reason,
        "min_crossings": len(current_map.roads), 
        "avg_time_per_crossing": duration / max(1, crossings) 
        } 
    with open("logs.json", "w") as f: 
        json.dump(log, f, indent=2) 
    print("Run complete:", log) 
    running = False


def record_risk(cooldown=None):
    global risk_events, last_risk_time
    local_cooldown = RISK_COOLDOWN_SECONDS if cooldown is None else cooldown
    if (time.time() - last_risk_time) > local_cooldown:
        risk_events += 1
        last_risk_time = time.time()


def is_car_approaching_player(car, player_rect):
    if car.vertical:
        dx = abs(car.rect.centerx - player_rect.centerx)
        if dx > 48:
            return False
        ahead = (player_rect.centery - car.rect.centery) * car.direction
        return 0 < ahead < 220 and car.current_speed > car.base_speed * 0.35
    dy = abs(car.rect.centery - player_rect.centery)
    if dy > 48:
        return False
    ahead = (player_rect.centerx - car.rect.centerx) * car.direction
    return 0 < ahead < 220 and car.current_speed > car.base_speed * 0.35

# --- Game Loop ---
while running:
    clock.tick(60)
    keys = pygame.key.get_pressed()
    elapsed = time.time() - start_time
    time_left = max(0, ROUND_TIME_LIMIT - elapsed)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    previous_pos = player.rect.topleft

    for state in road_states:
        state["light_state"] = get_light_state(elapsed + state["phase_offset"])
        state["player_waiting"] = False
        road_rect = state["road_rect"]
        crosswalk = state["crosswalk"]
        wait_zone = crosswalk.inflate(80, 80)
        if wait_zone.colliderect(player.rect) and not road_rect.colliderect(player.rect):
            state["player_waiting"] = True

    # Crossing logic
    for road in current_map.roads:
        if road.rect.colliderect(player.rect) and not road.crossed:
            if road.direction == "vertical":
                # Player must move vertically across
                if player.rect.top < road.rect.top:
                    crossings += 1
                    road.crossed = True
            elif road.direction == "horizontal":
                # Player must move horizontally across
                if player.rect.left > road.rect.left:
                    crossings += 1
                    road.crossed = True
        # Car spawning logic
        if road.direction == "vertical":
            if abs(player.rect.centery - road.rect.centery) < 300 and random.random() < 0.01: # testing spawn-zones
                try_spawn_car(road, cars, player, all_sprites)
        elif road.direction == "horizontal":
            if abs(player.rect.centerx - road.rect.centerx) < 300 and random.random() < 0.01: # testing spawn-zones 
                try_spawn_car(road, cars, player, all_sprites)

    # Update
    player.update(keys)
    if not world_bounds.contains(player.rect):
        player.rect.topleft = previous_pos

    cars.update(cars.sprites(), road_states, world_bounds, intersection_zones, player.rect)

    player_on_crosswalk = any(state["crosswalk"].colliderect(player.rect) for state in road_states)
    player_on_road = any(road.rect.colliderect(player.rect) for road in current_map.roads)
    nearby_fast_cars = [car for car in cars if car.rect.colliderect(player.rect.inflate(170, 170)) and car.current_speed > car.base_speed * 0.65]
    approaching_cars = [car for car in cars if is_car_approaching_player(car, player.rect)]

    if player_on_road and not player_on_crosswalk and nearby_fast_cars:
        record_risk()
    if player_on_crosswalk and approaching_cars:
        crosswalk_red = any(
            state["crosswalk"].colliderect(player.rect) and state["light_state"] == "red"
            for state in road_states
        )

        # Only count as risk if it's NOT a red light for cars,
        # or if cars are still moving dangerously despite red.
        dangerous_cars = [
            car for car in approaching_cars
            if car.current_speed > car.base_speed * 0.25
        ]

        if not crosswalk_red or dangerous_cars:
            record_risk()
        if any(car.rect.colliderect(player.rect.inflate(TOO_CLOSE_DISTANCE, TOO_CLOSE_DISTANCE)) for car in cars):
            record_risk(cooldown=0.7)
        if any(car.rect.colliderect(player.rect.inflate(NEAR_MISS_DISTANCE, NEAR_MISS_DISTANCE)) and car.current_speed > car.base_speed * 0.75 for car in cars):
            record_risk()

    # Collision check
    if pygame.sprite.spritecollideany(player, cars):
        end_game(True, timed_out=False)

    # Crossing check (player reaches goal)
    if player.rect.colliderect(current_map.goal_rect):
        end_game(False, timed_out=False)

    if time_left <= 0 and running:
        end_game(False, timed_out=True)

    camera_offset = (player.rect.centerx - WIDTH//2, player.rect.centery - HEIGHT//2)
        
    # Draw
    screen.fill((255, 255, 255)) 
    current_map.draw(screen, camera_offset, player) 
    for state in road_states:
        shifted_crosswalk = state["crosswalk"].move(-camera_offset[0], -camera_offset[1])
        pygame.draw.rect(screen, (240, 240, 240), shifted_crosswalk, 0)
        for stripe in range(0, shifted_crosswalk.width if shifted_crosswalk.width > shifted_crosswalk.height else shifted_crosswalk.height, 12):
            if shifted_crosswalk.width > shifted_crosswalk.height:
                pygame.draw.line(screen, (190, 190, 190), (shifted_crosswalk.left + stripe, shifted_crosswalk.top), (shifted_crosswalk.left + stripe, shifted_crosswalk.bottom), 2)
            else:
                pygame.draw.line(screen, (190, 190, 190), (shifted_crosswalk.left, shifted_crosswalk.top + stripe), (shifted_crosswalk.right, shifted_crosswalk.top + stripe), 2)

        shifted_sign = state["sign_rect"].move(-camera_offset[0], -camera_offset[1])
        sign_color = (35, 90, 200) if state["direction"] == "vertical" else (200, 120, 25)
        sign_label = "V" if state["direction"] == "vertical" else "H"
        pygame.draw.rect(screen, sign_color, shifted_sign, border_radius=3)
        pygame.draw.rect(screen, (25, 25, 25), shifted_sign, width=1, border_radius=3)
        sign_text = sign_font.render(sign_label, True, (255, 255, 255))
        sign_text_rect = sign_text.get_rect(center=shifted_sign.center)
        screen.blit(sign_text, sign_text_rect)
        if state["direction"] == "vertical":
            housing = pygame.Rect(shifted_crosswalk.centerx - 11, shifted_crosswalk.top - 68, 22, 56)
        else:
            housing = pygame.Rect(shifted_crosswalk.left - 68, shifted_crosswalk.centery - 11, 56, 22)

        pygame.draw.rect(screen, (25, 25, 25), housing, border_radius=5)
        pygame.draw.rect(screen, (70, 70, 70), housing, width=2, border_radius=5)

        if state["direction"] == "vertical":
            bulb_positions = [
                (housing.centerx, housing.top + 10),
                (housing.centerx, housing.top + 28),
                (housing.centerx, housing.top + 46),
            ]
        else:
            bulb_positions = [
                (housing.left + 10, housing.centery),
                (housing.left + 28, housing.centery),
                (housing.left + 46, housing.centery),
            ]

        red_on = state["light_state"] == "red"
        yellow_on = state["light_state"] == "yellow"
        green_on = state["light_state"] == "green"
        bulb_colors = [
            (220, 30, 30) if red_on else (80, 20, 20),
            (235, 185, 40) if yellow_on else (85, 70, 20),
            (40, 200, 40) if green_on else (20, 80, 20),
        ]
        for pos, color in zip(bulb_positions, bulb_colors):
            pygame.draw.circle(screen, color, pos, 6)

    for wall in wall_rects:
        shifted_wall = wall.move(-camera_offset[0], -camera_offset[1])
        pygame.draw.rect(screen, (40, 40, 40), shifted_wall)

    for sprite in all_sprites: 
        shifted_rect = sprite.rect.move(-camera_offset[0], -camera_offset[1]) 
        screen.blit(sprite.image, shifted_rect) 

    hud_lines = [
        f"Time left: {time_left:05.1f}s",
        f"Crossings: {crossings}/{len(current_map.roads)}",
        f"Risky moves: {risk_events}",
    ]
    for idx, line in enumerate(hud_lines):
        text_surface = font.render(line, True, HUD_TEXT_COLOR)
        screen.blit(text_surface, (10, 10 + idx * 24))

    pygame.display.flip()

pygame.quit()
