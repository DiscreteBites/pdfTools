from typing import List, Optional, Tuple, cast

import fitz  # PyMuPDF
from fitz import Page, Rect

Line = Tuple[float, float]

HORIZONTAL_PADDING: float = 6.0         # pts
VERTICAL_PADDING: float = 6.0           # pts

def get_content_rect(page: Page) -> Rect:
    """Find content bounds."""
    rect = page.rect
    rects: List[Rect] = []

    # text blocks
    for b in page.get_text("blocks"):
        rects.append(Rect(b[:4]))
    
    # drawings (vector graphics, lines, borders, etc.)
    for d in page.get_drawings():
        r = d.get("rect")
        if r is not None:
            rects.append(r)


    # include images
    for img in page.get_images(full=True):
        name = img[7]
        try:
            img_rect = cast(Rect, page.get_image_bbox(name))
            rects.append(img_rect)
        except ValueError:
            # image might not actually be placed on this page
            pass

    if not rects:
        return rect

    # Create Union of all content rects
    content_rect = rects[0]
    for r in rects[1:]:
        content_rect |= r
    
    # Create a new rect with the cropped distances
    return Rect(
        max(rect.x0, content_rect.x0 - HORIZONTAL_PADDING),
        max(rect.y0, content_rect.y0 - VERTICAL_PADDING),
        min(rect.x1, content_rect.x1 + HORIZONTAL_PADDING),
        min(rect.y1, content_rect.y1 + VERTICAL_PADDING)
    )

def overlaps(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)

def merge_y_overlaps(lines: List[Line], joins: List[Line] = [], tol: float = 0.4) -> List[Line]:
    glyphs = [*[("line", *line) for line in lines], *[("join", *join) for join in joins]]

    num_glyphs = len(glyphs)
    glyphs.sort(key = lambda b: b[1])

    merged_glyphs: List[Line] = []
    glyph_cursor: int = 0
    
    while glyph_cursor < num_glyphs:
        
        seed = glyphs[glyph_cursor]
        active_top = seed[1]
        active_bot = seed[2]
        
        merge_cursor = glyph_cursor + 1
        look_ahead = 0
        look_ahead_bot = active_bot
        
        join_regions = [[active_top, active_bot]] if seed[0] == "join" else []

        while merge_cursor + look_ahead < num_glyphs:
            test_glyph = glyphs[merge_cursor + look_ahead]
            box_type, y0, y1 = test_glyph

            # Keep checking until top of merge box is below active_bot
            if y0 > active_bot:
                break
            
            should_merge = False

            # Using join to merge should only occur if the test glyph overlaps any join region within the active zone.
            join_overlap = any([overlaps(join[0], join[1], y0, y1) > 0 for join in join_regions]) if box_type != "join" else True
            
            # Check for overlap merge
            overlap = overlaps(active_top, active_bot, y0, y1)
            ratio = overlap / min(active_bot - active_top, y1 - y0) if overlap > 0 else 0

            # If the current box is a JOIN then just always join if overlap > 0 since that is its own overlap
            should_merge = ( 
                join_overlap
                or (overlap > 0 and (box_type == 'join'))
                or (ratio >= tol)
            )

            if not should_merge:
                look_ahead_bot = max(look_ahead_bot, y1)
                look_ahead += 1
                continue
            
            # Case: Do merge
            active_bot = max(active_bot, look_ahead_bot, y1)
            merge_cursor += look_ahead +1

            look_ahead = 0
            look_ahead_bot = active_bot
            
            # Merge join box regions
            if box_type == 'join':
                if not join_regions or join_regions[-1][1] < y0:
                    join_regions.append([y0, y1])
                elif join_regions[-1][1] < y1:
                    join_regions[-1][1] = y1

        merged_glyphs.append((active_top, active_bot))
        glyph_cursor = merge_cursor

    return merged_glyphs

input_pdf = r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Electrodynamics\Electrodynamics - Challinor_wtoc.pdf"
output_pdf = "electro_debug_lines.pdf"

doc = fitz.open(input_pdf)

for page in doc:

    content_rect = get_content_rect(page)

    # Extract Drawings
    drawings = page.get_drawings()
    # Extract structured text
    text_dict = page.get_text("dict")

    rects = []
    lines: List[Line] = []
    joins: List[Line] = []

    page.draw_rect(
        content_rect,
        color=(0.5, 0.5, 0.5), # mid grey
        width=0.5
    )    

    for d in drawings:
        pad = 3
        rect = d['rect']
        joins.append((rect.y0 -pad, rect.y1 +pad))

        page.draw_rect(
            rect,
            color=(0, 0, 1),  # blue
            width=0.3
        )
        
        # Optional: visualize forbidden zone
        band = fitz.Rect(rect.x0 -pad, rect.y0 -pad, rect.x1 +pad, rect.y1 +pad)
        page.draw_rect(
            band,
            color=(0, 1, 0), # green
            width=0.3
        )
        
        # Optional: label line index for debugging
        page.insert_text(
            (rect.x0, rect.y0 - 2),
            " ".join([str(item[0]) for item in d['items']]),
            fontsize=6,
            color=(0, 0, 1) # blue
        )

    for block in text_dict["blocks"]: # pyright: ignore[reportArgumentType, reportCallIssue]
            if block["type"] == 0: # pyright: ignore[reportArgumentType]
                for line in block["lines"]: # pyright: ignore[reportArgumentType]
                    lines.append((line["bbox"][1], line["bbox"][3])) # pyright: ignore[reportArgumentType]
                    rects.append(line["bbox"]) # pyright: ignore[reportArgumentType]
            else:
                lines.append((block["bbox"][1], block["bbox"][3])) # pyright: ignore[reportArgumentType]
                rects.append(block["bbox"]) # pyright: ignore[reportArgumentType]

    for rect in rects:
        # Line bounding box
        rect = fitz.Rect(rect) # pyright: ignore[reportArgumentType]

        # Draw rectangle around the drawing
        page.draw_rect(
            rect,
            color=(1, 0, 0),   # red
            width=0.5
        )

    merged_glyphs = merge_y_overlaps(lines, joins)

    for idx, line in enumerate(merged_glyphs):
        y0, y1 = line

        rect = fitz.Rect()

        offset = lambda idx: 0 if idx % 2 == 1 else 11

        page.draw_line(
            fitz.Point(0, y0),
            fitz.Point(page.rect.width, y0),
            color=(0, 1, 1),    #cyan
            width=0.5,
            dashes="4 4"
        )
        page.insert_text(
            (offset(idx), y0 - 2),
            f"{idx}t",
            fontsize=6,
            color=(0, 1, 1) # cyan
        )
        
        page.draw_line(
            fitz.Point(0, y1),
            fitz.Point(page.rect.width, y1),
            color=(1, 0, 1),    #magenta
            width=0.5,
            dashes="4 4"
        )
        page.insert_text(
            (24 + offset(idx), y1 - 2),
            f"{idx}b",
            fontsize=6,
            color=(1, 0, 1) #magenta 
        )

doc.save(output_pdf)
doc.close()

print(f"Saved debug PDF to {output_pdf}")
