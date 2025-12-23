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

def get_line_char(dx, dy):
    abs_dx = abs(dx)
    abs_dy = abs(dy)

    # pick ascii character based on slope
    if abs_dx > abs_dy * 3:
        return ord('-')
    elif abs_dy > abs_dx * 3:
        return ord('|')
    elif abs_dx > abs_dy / 3 and abs_dy > abs_dx / 3:
        if (dx > 0 and dy > 0) or (dx < 0 and dy < 0):
            return ord('\\') 
        else:
            return ord('/')
    else:
        return ord('#')

def fill_poly_scanline(stdscr, poly_coords, cam_x, cam_y, zoom, aspect_ratio, width, height, char_color):
    # convert to screen coordinates
    screen_poly = []
    cx, cy = width // 2, height // 2
    min_y, max_y = height, 0

    for mx, my in poly_coords:
        tx = mx - cam_x
        ty = my - cam_y
        sx = int((tx * zoom * aspect_ratio) + cx)
        sy = int((-ty * zoom) + cy)
        screen_poly.append((sx, sy))
        if 0 <= sy < height:
            min_y = min(min_y, sy)
            max_y = max(max_y, sy)

    if not screen_poly: return

    # identify edges + scanlines
    edges = []
    num_points = len(screen_poly)
    for i in range(num_points):
        p1 = screen_poly[i]
        p2 = screen_poly[(i + 1) % num_points]
        if p1[1] == p2[1]: continue
        
        if p1[1] < p2[1]:
            edges.append((p1[1], p2[1], p1[0], (p2[0] - p1[0]) / (p2[1] - p1[1])))
        else:
            edges.append((p2[1], p1[1], p2[0], (p1[0] - p2[0]) / (p1[1] - p2[1])))

    # draw every 2nd line for hatching effect
    for y in range(max(0, min_y), min(height, max_y + 1), 2): 
        intersections = []
        for y1, y2, x_start, slope in edges:
            if y1 <= y < y2:
                intersections.append(x_start + slope * (y - y1))
        
        intersections.sort()
        for i in range(0, len(intersections) - 1, 2):
            x_start = int(intersections[i])
            x_end = int(intersections[i+1])
            
            if x_end > 0 and x_start < width:
                draw_line(stdscr, max(0, x_start), y, min(width-1, x_end), y, char_color)

def draw_line(stdscr, x0, y0, x1, y1, char_attr):
    height, width = stdscr.getmaxyx()
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)

    # Cohen-Sutherland Line Clipping 
    INSIDE, LEFT, RIGHT, BOTTOM, TOP = 0, 1, 2, 4, 8

    def compute_out_code(x, y):
        code = INSIDE
        if x < 0: code |= LEFT
        elif x >= width: code |= RIGHT
        if y < 0: code |= TOP  # curses y=0 is top
        elif y >= height: code |= BOTTOM
        return code

    code0 = compute_out_code(x0, y0)
    code1 = compute_out_code(x1, y1)

    while True:
        if not (code0 | code1): # Both inside
            break
        if code0 & code1: # Both outside same region
            return 
        
        # Calculate intersection
        code_out = code0 if code0 else code1
        x, y = 0, 0
        
        if code_out & BOTTOM:
            x = x0 + (x1 - x0) * (height - 1 - y0) / (y1 - y0)
            y = height - 1
        elif code_out & TOP:
            x = x0 + (x1 - x0) * (0 - y0) / (y1 - y0)
            y = 0
        elif code_out & RIGHT:
            y = y0 + (y1 - y0) * (width - 1 - x0) / (x1 - x0)
            x = width - 1
        elif code_out & LEFT:
            y = y0 + (y1 - y0) * (0 - x0) / (x1 - x0)
            x = 0

        if code_out == code0:
            x0, y0 = int(x), int(y)
            code0 = compute_out_code(x0, y0)
        else:
            x1, y1 = int(x), int(y)
            code1 = compute_out_code(x1, y1)

    # Fast Bresenham
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    while True:
        try: stdscr.addch(y0, x0, char_attr)
        except: pass 
        
        if x0 == x1 and y0 == y1: break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy

def draw_projected_polyline(stdscr, coords_mx_my, cam_x, cam_y, zoom, aspect_ratio, width, height, char_color):
    screen_points = []
    cx, cy = width // 2, height // 2

    # project to screnspace
    for mx, my in coords_mx_my:
        # transalte based on camera
        tx = mx - cam_x
        ty = my - cam_y
        # to screen space
        sx = (tx * zoom * aspect_ratio) + cx
        sy = (-ty * zoom) + cy
        
        screen_points.append((int(sx), int(sy)))

    # draw lines and clippings
    for i in range(len(screen_points) - 1):
        p1 = screen_points[i]
        p2 = screen_points[i+1]
        
        # simple bounds check to save perf
        if (0 <= p1[0] < width and 0 <= p1[1] < height) or \
           (0 <= p2[0] < width and 0 <= p2[1] < height):
            draw_line(stdscr, p1[0], p1[1], p2[0], p2[1], char_color)

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
        
        # keep the point if it's far enough from the last point
        if dist_sq >= tolerance_sq:
            simplified.append(current_point)
            last_point = current_point
            
    if simplified[-1] != coords_mx_my[-1]:
        simplified.append(coords_mx_my[-1])
        
    return simplified


# simplifcaiton helper for countries
def draw_country_poly(stdscr, poly_coords, cam_x, cam_y, zoom, aspect_ratio, width, height, color, simplify_tolerance=0.0):
    coords_to_draw = poly_coords
    # tolerance
    if simplify_tolerance > 0.0:
        coords_to_draw = simplify_polyline(poly_coords, simplify_tolerance)
        
    screen_points = []
    cx, cy = width // 2, height // 2
    for mx, my in coords_to_draw:
        tx = mx - cam_x
        ty = my - cam_y
        sx = (tx * zoom * aspect_ratio) + cx
        sy = (-ty * zoom) + cy
        screen_points.append((int(sx), int(sy)))
        
    # draw lines loop
    for i in range(len(screen_points) - 1):
        p1 = screen_points[i]
        p2 = screen_points[i+1]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        char = get_line_char(dx, dy)
        
        draw_line(stdscr, p1[0], p1[1], p2[0], p2[1], char | color)
    
    # close loop
    if screen_points:
        p1 = screen_points[-1]
        p2 = screen_points[0]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        char = get_line_char(dx, dy)
        draw_line(stdscr, p1[0], p1[1], p2[0], p2[1], char | color)