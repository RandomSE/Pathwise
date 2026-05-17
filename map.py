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
