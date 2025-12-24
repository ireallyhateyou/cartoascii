import math
import numpy as np

class BrailleBuffer:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.cols = width // 2
        self.rows = height // 4
        
        # 0x2800 is the unicode offset for braille patterns
        self.braille_base = 0x2800
        
        # Map 2x4 pixel grid to Braille bitmasks
        # Using numpy array for vector-like access if needed later
        self.pixel_map = np.array([
            [0x1, 0x8],
            [0x2, 0x10],
            [0x4, 0x20],
            [0x40, 0x80]
        ], dtype=np.uint8)
        
        # NumPy grids for speed (much faster than list of lists)
        self.buffer = np.zeros((self.rows, self.cols), dtype=np.uint8)
        self.colors = np.zeros((self.rows, self.cols), dtype=np.uint8)

    def clear(self):
        # numpy clear is instant
        self.buffer.fill(0)
        self.colors.fill(0)

    def set_pixel(self, x, y, color_pair=0):
        # bounds check
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return

        # bitmask calc
        char_x = x >> 1  
        char_y = y >> 2 
        
        if char_x >= self.cols or char_y >= self.rows: 
            return

        sub_x = x & 1    # mod 2
        sub_y = y & 3    # mod 4

        # direct array access
        self.buffer[char_y, char_x] |= self.pixel_map[sub_y, sub_x]
        
        # apply color (last write wins)
        if color_pair:
            self.colors[char_y, char_x] = color_pair

    def frame(self):
        # Optimized frame generation
        output_lines = []
        
        # iterate rows
        for y in range(self.rows):
            line_chars = []
            row_buf = self.buffer[y]
            row_col = self.colors[y]
            
            for x in range(self.cols):
                # FORCE INT CAST HERE to prevent OverflowError
                val = int(row_buf[x])
                
                if val == 0:
                    line_chars.append((" ", 0))
                else:
                    # 0x2800 + bitmask = Braille Character
                    # Now safe because val is a standard python int
                    line_chars.append((chr(self.braille_base + val), int(row_col[x])))
            output_lines.append(line_chars)
            
        return output_lines