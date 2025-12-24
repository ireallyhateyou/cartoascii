import math
import numpy as np
from numba import jit

@jit(nopython=True)
def fast_set_pixel(buffer_arr, colors_arr, z_buf_arr, x, y, color, z_index, pixel_map):
    rows, cols = buffer_arr.shape
    
    # bounds check
    char_x = x >> 1
    char_y = y >> 2
    
    if char_x < 0 or char_x >= cols or char_y < 0 or char_y >= rows:
        return

    sub_x = x & 1
    sub_y = y & 3
    
    # z-buffer check (priority)
    current_z = z_buf_arr[char_y, char_x]
    
    # always write geometry
    buffer_arr[char_y, char_x] |= pixel_map[sub_y, sub_x]
    
    # only write color/z if we are on top
    if z_index >= current_z:
        if color > 0:
            colors_arr[char_y, char_x] = color
            z_buf_arr[char_y, char_x] = z_index

class BrailleBuffer:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.cols = width // 2
        self.rows = height // 4
        
        # 0x2800 is the unicode offset for braille patterns
        self.braille_base = 0x2800
        
        # Map 2x4 pixel grid to Braille bitmasks
        self.pixel_map = np.array([
            [0x1, 0x8],
            [0x2, 0x10],
            [0x4, 0x20],
            [0x40, 0x80]
        ], dtype=np.uint8)
        
        # NumPy grids for speed
        self.buffer = np.zeros((self.rows, self.cols), dtype=np.uint8)
        self.colors = np.zeros((self.rows, self.cols), dtype=np.uint8)
        self.z_buffer = np.zeros((self.rows, self.cols), dtype=np.uint8)

    def clear(self):
        # numpy clear is instant
        self.buffer.fill(0)
        self.colors.fill(0)
        self.z_buffer.fill(0)

    def set_pixel(self, x, y, color_pair=0, z_index=0):
        # dispatch to numba
        fast_set_pixel(
            self.buffer, self.colors, self.z_buffer, 
            int(x), int(y), int(color_pair), int(z_index), 
            self.pixel_map
        )

    def frame(self):
        # Optimized frame generation
        output_lines = []
        
        # iterate rows
        for y in range(self.rows):
            line_chars = []
            row_buf = self.buffer[y]
            row_col = self.colors[y]
            
            for x in range(self.cols):
                val = int(row_buf[x])
                
                if val == 0:
                    line_chars.append((" ", 0))
                else:
                    # 0x2800 + bitmask = Braille Character
                    line_chars.append((chr(self.braille_base + val), int(row_col[x])))
            output_lines.append(line_chars)
            
        return output_lines