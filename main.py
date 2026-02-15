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

# --- Init ---
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Pathwise MVP")
clock = pygame.time.Clock()

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
        self.speed = speed
        self.vertical = vertical

    def update(self):
        if self.vertical:
            self.rect.y += self.speed
        else:
            self.rect.x += self.speed
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
running = True

def end_game(collided): 
    global crossings, collisions, running 
    end_time = time.time() 
    duration = round(end_time - start_time, 2) 
    if collided: 
        collisions += 1 
    log = { 
        "time": duration, 
        "crossings": crossings, 
        "collisions": collisions, 
        "min_crossings": len(current_map.roads), 
        "avg_time_per_crossing": duration / max(1, crossings) 
        } 
    with open("logs.json", "w") as f: 
        json.dump(log, f, indent=2) 
    print("Run complete:", log) 
    running = False

# --- Game Loop ---
while running:
    clock.tick(60)
    keys = pygame.key.get_pressed()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

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
                # Cars drive left/right
                side = random.choice(["left", "right"])
                y = road.rect.y + random.randint(0, road.rect.height - CAR_HEIGHT)
                speed = CAR_SPEED if side == "left" else -CAR_SPEED
                x = -CAR_WIDTH if side == "left" else WIDTH*2
                car = Car(x, y, speed)
                cars.add(car)
                all_sprites.add(car)
        elif road.direction == "horizontal":
            if abs(player.rect.centerx - road.rect.centerx) < 300 and random.random() < 0.01: # testing spawn-zones 
            # Cars drive up/down
                side = random.choice(["top", "bottom"])
                x = road.rect.x + random.randint(0, road.rect.width - CAR_WIDTH)
                speed = CAR_SPEED if side == "top" else -CAR_SPEED
                y = -CAR_HEIGHT if side == "top" else WIDTH*2
                car = Car(x, y, speed, vertical=True)  # mark vertical cars
                cars.add(car)
                all_sprites.add(car)

    # Update
    player.update(keys)
    cars.update()

    # Collision check
    if pygame.sprite.spritecollideany(player, cars):
        end_game(True)

    # Crossing check (player reaches goal)
    if player.rect.colliderect(current_map.goal_rect): 
        end_game(False)

    camera_offset = (player.rect.centerx - WIDTH//2, player.rect.centery - HEIGHT//2)
        
    # Draw
    screen.fill((255, 255, 255)) 
    current_map.draw(screen, camera_offset, player) 
    for sprite in all_sprites: 
        shifted_rect = sprite.rect.move(-camera_offset[0], -camera_offset[1]) 
        screen.blit(sprite.image, shifted_rect) 
    pygame.display.flip()

pygame.quit()
