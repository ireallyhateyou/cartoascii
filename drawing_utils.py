import curses
import math

mercator_const = 85.051129

class LabelManager:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.occupied = [] # list of (x, y, w, h)

    def can_draw(self, x, y, text_len):
        # simple bounding box check
        x1, y1 = x - 1, y - 1
        x2, y2 = x + text_len + 1, y + 1
        
        # screen bounds
        if x1 < 0 or y1 < 0 or x2 >= self.width or y2 >= self.height:
            return False

        for (ox, oy, ow, oh) in self.occupied:
            # check intersection
            if not (x2 < ox or x1 > ox + ow or y2 < oy or y1 > oy + oh):
                return False # overlap
        
        return True

    def register(self, x, y, text_len):
        self.occupied.append((x, y, text_len, 1))


def draw_progress_bar(stdscr, y, x, width, percent, message):
    bar_width = width - 4
    filled = int(bar_width * (percent / 100.0))
    bar = "[" + "#" * filled + "." * (bar_width - filled) + "]"
    stdscr.addstr(y, x, message, curses.color_pair(3))
    stdscr.addstr(y + 1, x, bar, curses.color_pair(6))

def text_input(stdscr, y, x, prompt):
    curses.echo()
    curses.curs_set(1)
    stdscr.addstr(y, x, prompt, curses.color_pair(3) | curses.A_BOLD)
    stdscr.refresh()
    
    # Read bytes and decode
    inp = stdscr.getstr(y, x + len(prompt), 30)
    
    curses.noecho()
    curses.curs_set(0)
    return inp.decode('utf-8')

def mercator_project(lat, lon):
    # clip
    if lat > mercator_const: lat = mercator_const
    if lat < -mercator_const: lat = -mercator_const
    x = lon
    
    # mercator formula
    lat_rad = math.radians(lat)
    y = math.log(math.tan((math.pi / 4) + (lat_rad / 2)))
    y = math.degrees(y)
    
    return x, y

def mercator_unproject(y_proj):
    y_proj_norm = math.radians(y_proj)
    lat_rad = 2 * (math.atan(math.exp(y_proj_norm)) - (math.pi / 4))
    return math.degrees(lat_rad)

def draw_line_braille(buffer, x0, y0, x1, y1, color, z_index=0):
    # bresenham adapted for the buffer
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    while True:
        buffer.set_pixel(x0, y0, color, z_index)
        
        if x0 == x1 and y0 == y1: break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy

def draw_projected_polyline_braille(buffer, coords, cam_x, cam_y, zoom, aspect_ratio, width, height, color, z_index=0):
    cx, cy = width // 2, height // 2
    screen_points = []
    
    for mx, my in coords:
        tx = mx - cam_x
        ty = my - cam_y
        sx = (tx * zoom * aspect_ratio * 2) + cx
        sy = (-ty * zoom * 4) + cy
        screen_points.append((int(sx), int(sy)))

    for i in range(len(screen_points) - 1):
        p1 = screen_points[i]
        p2 = screen_points[i+1]
        
        # bounds
        if (0 <= p1[0] < width or 0 <= p1[1] < height):
             draw_line_braille(buffer, p1[0], p1[1], p2[0], p2[1], color, z_index)

def simplify_polyline(coords_mx_my, tolerance_mx_my):
    if not coords_mx_my:
        return []
    
    simplified = [coords_mx_my[0]]
    last_point = coords_mx_my[0]
    
    tolerance_sq = tolerance_mx_my * tolerance_mx_my
    
    for i in range(1, len(coords_mx_my)):
        current_point = coords_mx_my[i]
        
        dx = current_point[0] - last_point[0]
        dy = current_point[1] - last_point[1]
        dist_sq = dx*dx + dy*dy
        
        if dist_sq >= tolerance_sq:
            simplified.append(current_point)
            last_point = current_point
            
    if simplified[-1] != coords_mx_my[-1]:
        simplified.append(coords_mx_my[-1])
        
    return simplified


def draw_menu(stdscr, title, options):
    # simple popup menu
    h, w = stdscr.getmaxyx()
    
    # dimensions
    menu_h = len(options) + 4
    menu_w = max([len(x) for x in options]) + 10
    if len(title) + 4 > menu_w: menu_w = len(title) + 4
    
    start_y = h // 2 - menu_h // 2
    start_x = w // 2 - menu_w // 2
    
    current_idx = 0
    
    while True:
        # clear area logic (simple box)
        for y in range(menu_h):
            stdscr.addstr(start_y + y, start_x, " " * menu_w, curses.color_pair(9))
        
        # border
        stdscr.attron(curses.color_pair(6))
        stdscr.addstr(start_y, start_x, "+" + "-" * (menu_w - 2) + "+")
        stdscr.addstr(start_y + menu_h - 1, start_x, "+" + "-" * (menu_w - 2) + "+")
        for y in range(1, menu_h - 1):
            stdscr.addstr(start_y + y, start_x, "|")
            stdscr.addstr(start_y + y, start_x + menu_w - 1, "|")
        stdscr.attroff(curses.color_pair(6))
        
        # title
        stdscr.addstr(start_y + 1, start_x + 2, title, curses.color_pair(6) | curses.A_BOLD)
        stdscr.addstr(start_y + 2, start_x + 1, "-" * (menu_w - 2), curses.color_pair(3))

        # options
        for i, opt in enumerate(options):
            style = curses.color_pair(3)
            prefix = "  "
            if i == current_idx:
                style = curses.color_pair(7) | curses.A_BOLD 
                prefix = "> "
            
            stdscr.addstr(start_y + 3 + i, start_x + 2, f"{prefix}{opt}", style)
            
        stdscr.refresh()
        
        key = stdscr.getch()
        if key == curses.KEY_UP:
            current_idx = (current_idx - 1) % len(options)
        elif key == curses.KEY_DOWN:
            current_idx = (current_idx + 1) % len(options)
        elif key == 10 or key == 13: # Enter
            return current_idx
        elif key == 27 or key == ord('q'): # Escape
            return None
