import pygame
import math
import commonUtils

WIDTH = commonUtils.WIDTH
VERTICAL = commonUtils.VERTICAL
HORIZONTAL = commonUtils.HORIZONTAL
BASE_SIZE = 40
ROAD_THICKNESS = 90
ROAD_SPAN = int(WIDTH * 1.35)
ROAD_GAP = 150

class Road:
    def __init__(self, rect, direction):
        self.rect = rect
        self.crossed = False
        self.direction = direction

def make_rectangle(left, top, width, height):
    return pygame.Rect(left, top, width, height)

class MapBase:
    def __init__(self, roads, start_pos, goal_rect):
        self.roads = roads
        self.start_pos = start_pos
        self.goal_rect = goal_rect 

    def draw(self, surface, camera_offset, player):
        # Draw roads
        for road in self.roads:
            shifted = road.rect.move(-camera_offset[0], -camera_offset[1])
            pygame.draw.rect(surface, (100, 100, 100), shifted)

        # Draw goal
        shifted_goal = self.goal_rect.move(-camera_offset[0], -camera_offset[1])
        pygame.draw.rect(surface, (0, 0, 200), shifted_goal)

        # Draw arrow pointing to goal
        draw_arrow(surface, player, shifted_goal, camera_offset)


# --- Map Variants ---
class VerticalMap(MapBase):
    def __init__(self):
        roads = []
        top_start = 120
        for i in range(3):
            roads.append(Road(make_rectangle(0, top_start + ROAD_GAP * i, ROAD_SPAN, ROAD_THICKNESS), VERTICAL))
        start_pos = (ROAD_SPAN // 2, roads[-1].rect.bottom + 90)
        first_road = roads[0].rect
        goal_rect = pygame.Rect(ROAD_SPAN // 2 - 20, first_road.top - 70, BASE_SIZE, BASE_SIZE)
        super().__init__(roads, start_pos, goal_rect)

class HorizontalMap(MapBase):
    def __init__(self):
        roads = []
        left_start = 120
        for i in range(3):
            roads.append(Road(make_rectangle(left_start + ROAD_GAP * i, 0, ROAD_THICKNESS, ROAD_SPAN), HORIZONTAL))
        start_pos = (roads[0].rect.left - 70, ROAD_SPAN // 2)
        first_road = roads[-1].rect
        goal_rect = make_rectangle(first_road.right + 35, ROAD_SPAN // 2 - 20, BASE_SIZE, BASE_SIZE)
        super().__init__(roads, start_pos, goal_rect)

class MixedMap(MapBase):
    def __init__(self):
        # Two horizontal roads, then one vertical in a compact area
        roads = [
            Road(make_rectangle(170, 0, ROAD_THICKNESS, ROAD_SPAN), HORIZONTAL),
            Road(make_rectangle(330, 0, ROAD_THICKNESS, ROAD_SPAN), HORIZONTAL),
            Road(make_rectangle(0, 470, ROAD_SPAN, ROAD_THICKNESS), VERTICAL)
        ]
        # Start outside all roads to prevent spawn-kill.
        start_pos = (70, 650)
        last_vertical = roads[-1].rect
        goal_rect = make_rectangle(last_vertical.right - 240, last_vertical.top - (BASE_SIZE * 2), BASE_SIZE, BASE_SIZE)
        super().__init__(roads, start_pos, goal_rect)

def draw_arrow(surface, player, goal, camera_offset):
    # Position above player's head
    base_x = player.rect.centerx - camera_offset[0]
    base_y = player.rect.top - 50 - camera_offset[1]

    # Direction vector toward goal
    dx = goal.centerx - (player.rect.centerx - camera_offset[0])
    dy = goal.centery - (player.rect.centery - camera_offset[1])
    length = math.hypot(dx, dy)
    if length == 0:
        return
    dx /= length
    dy /= length

    # Line endpoint
    tip_x = base_x + dx * BASE_SIZE
    tip_y = base_y + dy * BASE_SIZE

    # Draw line
    pygame.draw.line(surface, (0,0,0), (base_x, base_y), (tip_x, tip_y), 3)

    # Arrowhead (two short lines angled off the tip)
    left_dx = dx * math.cos(math.pi/6) - dy * math.sin(math.pi/6)
    left_dy = dx * math.sin(math.pi/6) + dy * math.cos(math.pi/6)
    right_dx = dx * math.cos(-math.pi/6) - dy * math.sin(-math.pi/6)
    right_dy = dx * math.sin(-math.pi/6) + dy * math.cos(-math.pi/6)

    pygame.draw.line(surface, (0,0,0), (tip_x, tip_y),
                     (tip_x - left_dx*15, tip_y - left_dy*15), 3)
    pygame.draw.line(surface, (0,0,0), (tip_x, tip_y),
                     (tip_x - right_dx*15, tip_y - right_dy*15), 3)
