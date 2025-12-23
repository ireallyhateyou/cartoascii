import math

class BrailleBuffer:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.cols = width // 2
        self.rows = height // 4
        
        # 0x2800 is the unicode offset for braille patterns
        self.braille_base = 0x2800
        
        # Map 2x4 pixel grid to Braille bitmasks (standard Braille dot positions)
        # (0,0) (1,0) -> 0x1   0x8
        # (0,1) (1,1) -> 0x2   0x10
        # (0,2) (1,2) -> 0x4   0x20
        # (0,3) (1,3) -> 0x40  0x80
        self.pixel_map = [
            [0x1, 0x8],
            [0x2, 0x10],
            [0x4, 0x20],
            [0x40, 0x80]
        ]
        
        # The buffer stores the integer bitmask for each character cell
        self.buffer = [[0 for _ in range(self.cols)] for _ in range(self.rows)]
        self.colors = [[0 for _ in range(self.cols)] for _ in range(self.rows)]

    def clear(self):
        for y in range(self.rows):
            for x in range(self.cols):
                self.buffer[y][x] = 0
                self.colors[y][x] = 0

    def set_pixel(self, x, y, color_pair=0):
        # clamp coordinates
        if not (0 <= x < self.width and 0 <= y < self.height):
            return

        # figure out braille character based on pos
        char_x = int(x // 2)
        char_y = int(y // 4)
        sub_x = int(x % 2)
        sub_y = int(y % 4)

        if 0 <= char_x < self.cols and 0 <= char_y < self.rows:
            self.buffer[char_y][char_x] |= self.pixel_map[sub_y][sub_x]
            if color_pair:
                self.colors[char_y][char_x] = color_pair

    def set_text(self, x, y, text, color_pair=0):
        # pixels to character coords
        char_x = int(x // 2)
        char_y = int(y // 4)
        
        if 0 <= char_y < self.rows:
            for i, char in enumerate(text):
                if 0 <= char_x + i < self.cols:
                    pass

    def frame(self):
        # generate frames
        output_lines = []
        for y in range(self.rows):
            line_chars = []
            for x in range(self.cols):
                val = self.buffer[y][x]
                if val == 0:
                    line_chars.append((" ", self.colors[y][x]))
                else:
                    # 0x2800 + bitmask = Braille Character
                    line_chars.append((chr(self.braille_base + val), self.colors[y][x]))
            output_lines.append(line_chars)
        return output_lines