import os
from PIL import Image, ImageDraw, ImageFont

# Ensure the destination upload directory exists safely
os.makedirs("static/uploads", exist_ok=True)

# 🎨 1. Initialize a premium 512x512 high-density canvas block
img = Image.new("RGB", (512, 512), "#0B192C")
draw = ImageDraw.Draw(img)

# 🏪 2. Draw a luxury branded market icon outline framework
# Outer bounding crown border
draw.rectangle([20, 20, 492, 492], outline="#F59E0B", width=6)

# Storefront roof nodes
draw.polygon([(80, 140), (256, 60), (432, 140)], fill="#F59E0B")

# Commercial interior pillars (Fixed array values)
for x in range(100, 400, 60):
    draw.rectangle([x, 180, x+25, 340], fill="#3B82F6")

# Baseline support grid matrix
draw.rectangle([60, 340, 452, 360], fill="#F59E0B")

# 📝 3. Inject corporate text brand styling
try:
    font = ImageFont.truetype("arial.ttf", 22)
except IOError:
    font = ImageFont.load_default()

# Paint motto phrase text layout rows
motto_text = "Connecting Local Markets Online"
draw.text((256, 420), motto_text, fill="#FFFFFF", font=font, anchor="mm")

# 💾 4. Compile and seal file data records locally
img.save("static/uploads/bizhub-app-icon.png", "PNG")
print("✓ SUCCESS: App icon drawn locally and saved directly to static/uploads/bizhub-app-icon.png with zero network errors!")
