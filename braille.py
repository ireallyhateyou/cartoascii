import math

class BrailleBuffer:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.cols = width // 2
        self.rows = height // 4
        
        # 0x2800 is the unicode offset for braille patterns
        self.braille_base = 0x2800
        
        # Map 2x4 pixel grid to Braille bitmasks
        # optimized for lookups
        self.pixel_map = [
            [0x1, 0x8],
            [0x2, 0x10],
            [0x4, 0x20],
            [0x40, 0x80]
        ]
        
        # list of ints is faster than objs
        self.buffer = [[0] * self.cols for _ in range(self.rows)]
        self.colors = [[0] * self.cols for _ in range(self.rows)]

    def clear(self):
        # optimized clear, reset values vs new lists
        for y in range(self.rows):
            for x in range(self.cols):
                self.buffer[y][x] = 0
                self.colors[y][x] = 0

    def set_pixel(self, x, y, color_pair=0):
        # bounds check
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return

        # bitmask calc (faster than div)
        char_x = x >> 1  
        char_y = y >> 2 
        
        if char_x >= self.cols or char_y >= self.rows: 
            return

        sub_x = x & 1    # mod 2
        sub_y = y & 3    # mod 4

        # apply mask
        self.buffer[char_y][char_x] |= self.pixel_map[sub_y][sub_x]
        
        # apply color (last write wins)
        if color_pair:
            self.colors[char_y][char_x] = color_pair

    def frame(self):
        # generate frames
        output_lines = []
        for y in range(self.rows):
            line_chars = []
            buf_row = self.buffer[y]
            col_row = self.colors[y]
            
            for x in range(self.cols):
                val = buf_row[x]
                if val == 0:
                    line_chars.append((" ", 0))
                else:
                    # 0x2800 + bitmask = Braille Character
                    line_chars.append((chr(self.braille_base + val), col_row[x]))
            output_lines.append(line_chars)
        return output_lines