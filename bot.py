"""
Growtopia Pixel Art Discord Bot
Slash commands: /pixel [image] [width] [height]
                /reset_cooldown [user]
Results sent via DM with comparison, shelf preview, and shopping list.
5-hour cooldown per user. Server only. Owner bypass.
"""

import discord
from discord import app_commands
from dotenv import load_dotenv
import os
import json
import math
import io
import time
from PIL import Image, ImageDraw, ImageFont
from collections import Counter

load_dotenv()

# ============================================
# CONFIG
# ============================================
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 1159862057626247279  # Your Discord user ID
COOLDOWN_HOURS = 5

# Find the correct base directory
possible_paths = ["/app", "/home/container", os.path.dirname(os.path.abspath(__file__))]
BASE_DIR = None
for path in possible_paths:
    if os.path.exists(os.path.join(path, "sprites")):
        BASE_DIR = path
        break
if BASE_DIR is None:
    BASE_DIR = possible_paths[-1]

SPRITES_DIR = os.path.join(BASE_DIR, "sprites")
STATS_FILE = os.path.join(BASE_DIR, "item_stats.json")
SOLID_FILE = os.path.join(BASE_DIR, "solid_items.json")
SHELF_SPRITE = os.path.join(SPRITES_DIR, "Display Shelf.png")
SHELF_CHARCOAL = os.path.join(SPRITES_DIR, "Display Shelf Charcoal.png")
SPRITE_SIZE = 15
MAX_DIM = 70

user_cooldowns = {}

# ============================================
# LOAD DATA
# ============================================
print("Loading data...")
with open(SOLID_FILE) as f:
    solid_items = json.load(f)
with open(STATS_FILE) as f:
    all_stats = json.load(f)

item_stats = {}
for name in solid_items:
    if name in all_stats:
        item_stats[name] = {
            'avg': tuple(all_stats[name]['avg']),
            'variance': all_stats[name]['variance']
        }
print(f"  {len(item_stats)} items ready")

# ============================================
# HELPERS
# ============================================
def clean_name(name):
    return name.replace(':', '_').replace('/', '_').replace('\\', '_').replace('?', '_').replace('*', '_').replace('<', '_').replace('>', '_').replace('|', '_').replace('"', '_')

def color_distance(c1, c2):
    return math.sqrt(2*(c1[0]-c2[0])**2 + 4*(c1[1]-c2[1])**2 + 3*(c1[2]-c2[2])**2)

def match_pixels(img, pw, ph):
    if img.size != (pw, ph):
        img = img.resize((pw, ph), Image.NEAREST)
    pixels = img.load()
    
    cache_new = {}
    cache_old = {}
    grid_new = []
    grid_old = []

    for y in range(ph):
        row_new = []
        row_old = []
        for x in range(pw):
            px = pixels[x, y]
            
            if px not in cache_new:
                best, best_score = None, float('inf')
                for name, stats in item_stats.items():
                    d = color_distance(px, stats['avg'])
                    score = d + (stats['variance'] * 0.05)
                    if score < best_score:
                        best_score = score
                        best = name
                cache_new[px] = best
            row_new.append(cache_new[px])
            
            if px not in cache_old:
                best, best_d = None, float('inf')
                for name, stats in item_stats.items():
                    d = color_distance(px, stats['avg'])
                    if d < best_d:
                        best_d = d
                        best = name
                cache_old[px] = best
            row_old.append(cache_old[px])
            
        grid_new.append(row_new)
        grid_old.append(row_old)

    return grid_new, grid_old

def build_shelf_image(grid, w, h, shelf_path):
    ITEM_SIZE = 70
    SLOT_GAP = 5
    SHELF_SIZE = 192
    LEFT_PAD = 26
    TOP_PAD = 20
    BOTTOM_EXTRA = 15

    sprites = {}
    for row in grid:
        for name in row:
            if name not in sprites:
                path = os.path.join(SPRITES_DIR, f"{clean_name(name)}.png")
                if os.path.exists(path):
                    sprites[name] = Image.open(path).convert("RGBA").resize((ITEM_SIZE, ITEM_SIZE), Image.NEAREST)
                else:
                    sprites[name] = Image.new("RGBA", (ITEM_SIZE, ITEM_SIZE), (255, 0, 255, 255))

    shelf_bg = Image.open(shelf_path).convert("RGBA")
    if shelf_bg.size != (SHELF_SIZE, SHELF_SIZE):
        shelf_bg = shelf_bg.resize((SHELF_SIZE, SHELF_SIZE), Image.NEAREST)

    sw, sh = (w + 1) // 2, (h + 1) // 2
    total_w = sw * SHELF_SIZE
    total_h = sh * SHELF_SIZE

    img = Image.new("RGBA", (total_w, total_h), (50, 50, 50, 255))

    for sy in range(sh):
        for sx in range(sw):
            shelf = shelf_bg.copy()
            positions = [(sy*2, sx*2), (sy*2, sx*2+1), (sy*2+1, sx*2), (sy*2+1, sx*2+1)]
            left_x = LEFT_PAD
            right_x = LEFT_PAD + ITEM_SIZE + SLOT_GAP
            top_y = TOP_PAD
            bottom_y = TOP_PAD + ITEM_SIZE + SLOT_GAP + BOTTOM_EXTRA
            spots = [(left_x, top_y), (right_x, top_y), (left_x, bottom_y), (right_x, bottom_y)]

            for (gy, gx), (px, py) in zip(positions, spots):
                if gy < h and gx < w:
                    shelf.paste(sprites[grid[gy][gx]], (px, py), sprites[grid[gy][gx]])

            img.paste(shelf, (sx * SHELF_SIZE, sy * SHELF_SIZE))

    return img

def build_comparison(grid_new, grid_old, w, h, original_img):
    sprite_cache = {}

    def get_sprite(name, size):
        if (name, size) not in sprite_cache:
            path = os.path.join(SPRITES_DIR, f"{clean_name(name)}.png")
            if os.path.exists(path):
                sprite_cache[(name, size)] = Image.open(path).convert("RGBA").resize((size, size), Image.NEAREST)
            else:
                sprite_cache[(name, size)] = Image.new("RGBA", (size, size), (255, 0, 255, 255))
        return sprite_cache[(name, size)]

    def build_flat(grid):
        pw, ph = w * SPRITE_SIZE, h * SPRITE_SIZE
        preview = Image.new("RGBA", (pw, ph))
        for y in range(h):
            for x in range(w):
                preview.paste(get_sprite(grid[y][x], SPRITE_SIZE), (x * SPRITE_SIZE, y * SPRITE_SIZE))
        return preview

    pw, ph = w * SPRITE_SIZE, h * SPRITE_SIZE

    original = original_img.convert("RGBA").resize((pw, ph), Image.NEAREST)
    flat_new = build_flat(grid_new)
    flat_old = build_flat(grid_old)
    
    shelf_new = build_shelf_image(grid_new, w, h, SHELF_SPRITE)
    shelf_new_rgb = shelf_new.convert("RGBA").resize((pw, ph), Image.NEAREST)
    
    if os.path.exists(SHELF_CHARCOAL):
        shelf_charcoal = build_shelf_image(grid_new, w, h, SHELF_CHARCOAL)
        shelf_charcoal_rgb = shelf_charcoal.convert("RGBA").resize((pw, ph), Image.NEAREST)
    else:
        shelf_charcoal_rgb = Image.new("RGBA", (pw, ph), (50, 50, 50, 255))
    
    shelf_old = build_shelf_image(grid_old, w, h, SHELF_SPRITE)
    shelf_old_rgb = shelf_old.convert("RGBA").resize((pw, ph), Image.NEAREST)

    gap = 4
    total_w = pw * 3 + gap * 2
    total_h = ph * 2 + gap
    comp = Image.new("RGBA", (total_w, total_h), (30, 30, 30, 255))

    comp.paste(original, (0, 0))
    comp.paste(flat_new, (pw + gap, 0))
    comp.paste(flat_old, (pw * 2 + gap * 2, 0))
    comp.paste(shelf_new_rgb, (0, ph + gap))
    comp.paste(shelf_charcoal_rgb, (pw + gap, ph + gap))
    comp.paste(shelf_old_rgb, (pw * 2 + gap * 2, ph + gap))

    draw = ImageDraw.Draw(comp)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except:
        font = ImageFont.load_default()
    draw.text((5, 5), "ORIGINAL", fill=(255, 255, 0), font=font)
    draw.text((pw + gap + 5, 5), "ITEMS (NEW)", fill=(255, 255, 0), font=font)
    draw.text((pw * 2 + gap * 2 + 5, 5), "ITEMS (OLD)", fill=(255, 255, 0), font=font)
    draw.text((5, ph + gap + 5), "SHELF (NEW)", fill=(255, 255, 0), font=font)
    draw.text((pw + gap + 5, ph + gap + 5), "SHELF CHARCOAL", fill=(255, 255, 0), font=font)
    draw.text((pw * 2 + gap * 2 + 5, ph + gap + 5), "SHELF (OLD)", fill=(255, 255, 0), font=font)

    return comp

def build_shopping_txt(counts_new, counts_old, w, h):
    txt = f"Growtopia Pixel Art Shopping List\n"
    txt += f"Dimensions: {w}x{h} ({w*h} total pixels)\n"
    txt += f"{'=' * 50}\n\n"
    
    txt += f"NEW ALGORITHM ({len(counts_new)} unique items):\n"
    txt += f"{'-' * 30}\n"
    txt += f"{'Qty':>6}  Item\n"
    txt += f"{'-' * 30}\n"
    for item, qty in counts_new.most_common():
        txt += f"{qty:>6}x  {item}\n"
    
    txt += f"\n\nOLD ALGORITHM ({len(counts_old)} unique items):\n"
    txt += f"{'-' * 30}\n"
    txt += f"{'Qty':>6}  Item\n"
    txt += f"{'-' * 30}\n"
    for item, qty in counts_old.most_common():
        txt += f"{qty:>6}x  {item}\n"
    
    return txt

# ============================================
# BOT
# ============================================
class PixelBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

bot = PixelBot()

@bot.tree.command(name="pixel", description="Convert an image to Growtopia pixel art")
@app_commands.describe(
    image="Your image file (PNG/JPG)",
    width=f"Width in pixels (max {MAX_DIM})",
    height=f"Height in pixels (max {MAX_DIM})"
)
async def pixel(interaction: discord.Interaction, image: discord.Attachment, width: int = 70, height: int = 70):
    user_id = interaction.user.id
    
    # Cooldown check (owner bypass)
    if user_id != OWNER_ID and user_id in user_cooldowns:
        elapsed = time.time() - user_cooldowns[user_id]
        if elapsed < COOLDOWN_HOURS * 3600:
            remaining = COOLDOWN_HOURS * 3600 - elapsed
            hours = int(remaining // 3600)
            minutes = int((remaining % 3600) // 60)
            await interaction.response.send_message(
                f"Cooldown! Please wait {hours}h {minutes}m.",
                ephemeral=True
            )
            return
    
    if width > MAX_DIM or height > MAX_DIM:
        await interaction.response.send_message(
            f"Max dimensions are {MAX_DIM}x{MAX_DIM}. You requested {width}x{height}.",
            ephemeral=True
        )
        return
    
    if width < 1 or height < 1:
        await interaction.response.send_message("Dimensions must be at least 1x1.", ephemeral=True)
        return
    
    if not image.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        await interaction.response.send_message("Please upload a PNG/JPG/WEBP image.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    if interaction.guild is None:
        await interaction.followup.send("This bot can only be used in a server.", ephemeral=True)
        return
    
    try:
        img_bytes = await image.read()
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        
        grid_new, grid_old = match_pixels(img, width, height)
        comp = build_comparison(grid_new, grid_old, width, height, img)
        
        output = io.BytesIO()
        comp.save(output, format='PNG')
        output.seek(0)
        
        shelf_new = build_shelf_image(grid_new, width, height, SHELF_SPRITE)
        shelf_output = io.BytesIO()
        shelf_new.save(shelf_output, format='PNG')
        shelf_output.seek(0)
        
        counts_new = Counter()
        for row in grid_new:
            counts_new.update(row)
        counts_old = Counter()
        for row in grid_old:
            counts_old.update(row)
        
        txt_content = build_shopping_txt(counts_new, counts_old, width, height)
        txt_file = io.BytesIO(txt_content.encode('utf-8'))
        
        user_cooldowns[user_id] = time.time()
        
        try:
            dm = await interaction.user.create_dm()
            await dm.send(
                content=f"{width}x{height} | {len(counts_new)} items (new) | {len(counts_old)} items (old) | {width*height} total pixels",
                files=[
                    discord.File(output, filename=f"pixelart_{width}x{height}.png"),
                    discord.File(shelf_output, filename=f"shelf_new_{width}x{height}.png"),
                    discord.File(txt_file, filename=f"shopping_list_{width}x{height}.txt")
                ]
            )
            await interaction.followup.send("Check your DMs.", ephemeral=True)
        except:
            await interaction.followup.send(
                content="I couldn't DM you. Please open your DMs and try again.",
                ephemeral=True
            )
        
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

@bot.tree.command(name="reset_cooldown", description="Reset cooldown for a user (Owner only)")
@app_commands.describe(user="User to reset cooldown for (leave blank to reset all)")
async def reset_cooldown(interaction: discord.Interaction, user: discord.User = None):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Owner only.", ephemeral=True)
        return
    
    if user:
        user_cooldowns.pop(user.id, None)
        await interaction.response.send_message(f"Cooldown reset for {user.mention}.", ephemeral=True)
    else:
        user_cooldowns.clear()
        await interaction.response.send_message("All cooldowns reset.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Ready! Logged in as {bot.user}")
    print(f"Max dimensions: {MAX_DIM}x{MAX_DIM}")
    print(f"Cooldown: {COOLDOWN_HOURS} hours per user")
    print(f"Owner ID: {OWNER_ID}")

if __name__ == "__main__":
    if not TOKEN:
        print("DISCORD_TOKEN not found in .env!")
        exit(1)
    bot.run(TOKEN)
