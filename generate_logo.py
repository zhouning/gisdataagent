import matplotlib.pyplot as plt
import os

def create_logo(text, bg_color, text_color, filename):
    fig, ax = plt.subplots(figsize=(4, 1), dpi=100)
    fig.patch.set_alpha(0.0) # Transparent background
    ax.set_axis_off()
    
    # Add text
    ax.text(0.5, 0.5, text, 
            fontsize=24, 
            fontweight='bold', 
            color=text_color,
            ha='center', va='center',
            fontname='Microsoft YaHei')
    
    output_path = os.path.join("public", filename)
    plt.savefig(output_path, bbox_inches='tight', pad_inches=0.1, transparent=True)
    plt.close()
    print(f"Created: {output_path}")

# Create Light Mode Logo (Dark Text)
create_logo("Data Agent", "white", "#333333", "logo_light.png")

# Create Dark Mode Logo (Light Text)
create_logo("Data Agent", "black", "#FFFFFF", "logo_dark.png")
