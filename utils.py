import curses
import math

mercator_const = 85.051129

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
    # reverse of : y = math.log(math.tan((math.pi / 4) + (lat_rad / 2)))
    y_proj_norm = math.radians(y_proj)
    lat_rad = 2 * (math.atan(math.exp(y_proj_norm)) - (math.pi / 4))
    return math.degrees(lat_rad)

def draw_line(stdscr, x0, y0, x1, y1, char):
    # Bresenham's line algorithm
    # https://www.cs.drexel.edu/~popyack/Courses/CSP/Fa18/notes/08.3_MoreGraphics/Bresenham.html?CurrentSlide=2
    height, width = stdscr.getmaxyx()

    # dont go off boundaries
    if (x0 < 0 and x1 < 0) or (x0 >= width and x1 >= width): return
    if (y0 < 0 and y1 < 0) or (y0 >= height and y1 >= height): return

    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    while True:
        if 0 <= x0 < width and 0 <= y0 < height:
            try:
                stdscr.addch(int(y0), int(x0), char)
            except curses.error:
                pass
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy

def draw_projected_polyline(stdscr, coords_mx_my, cam_x, cam_y, zoom, aspect_ratio, width, height, char_color):
    screen_points = []

    # project to screnspace
    for mx, my in coords_mx_my:
        # transalte based on camera
        tx = mx - cam_x
        ty = my - cam_y
        # to screen space
        sx = (tx * zoom * aspect_ratio) + width // 2
        sy = (-ty * zoom) + height // 2
        
        screen_points.append((int(sx), int(sy)))

    # draw lines and clippings
    for i in range(len(screen_points) - 1):
        p1 = screen_points[i]
        p2 = screen_points[i+1]
        
        # bounds check
        if (0 <= p1[0] < width and 0 <= p1[1] < height) or \
           (0 <= p2[0] < width and 0 <= p2[1] < height):
            draw_line(stdscr, p1[0], p1[1], p2[0], p2[1], char_color)