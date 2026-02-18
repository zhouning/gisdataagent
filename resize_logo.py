from PIL import Image
import os

def resize_image(file_path, target_width=300):
    try:
        img = Image.open(file_path)
        print(f"Original size: {img.size}, file size: {os.path.getsize(file_path) / 1024:.2f} KB")
        
        # Calculate new height to maintain aspect ratio
        w_percent = (target_width / float(img.size[0]))
        h_size = int((float(img.size[1]) * float(w_percent)))
        
        # Resize
        img = img.resize((target_width, h_size), Image.Resampling.LANCZOS)
        
        # Save (optimize)
        img.save(file_path, optimize=True, quality=85)
        print(f"Resized to: {img.size}, new file size: {os.path.getsize(file_path) / 1024:.2f} KB")
        print("✅ Resize successful!")
        
    except Exception as e:
        print(f"❌ Error processing image: {e}")

if __name__ == "__main__":
    target_file = os.path.join("public", "logo_light.png")
    if os.path.exists(target_file):
        resize_image(target_file)
    else:
        print(f"File not found: {target_file}")
