from __future__ import annotations

import sys
from typing import Dict, List, Optional, Tuple, cast

import math
import fitz
from fitz import Page, Document, Rect

# ----------------------------
# Configuration
# ----------------------------
#
# Notes: 1pt = 1/72 inch.
# 
# 6" Kobo Clara BW: 4.8" x 3.6" 
#
# A4 aspect ratio: 1 x sqrt(2)
#
# So A 4:3 aspect ratio will cover A4 twice with change.
#
# Assume single wide column PDF, multicolumn PDF use a per column solution

TARGET_ASPECT_RATIO: tuple[float, float] = (4, 3)   # Width x Height
TARGET_ROTATION: int = -90              # degrees

HORIZONTAL_PADDING: float = 6.0         # pts
VERTICAL_PADDING: float = 6.0           # pts
s
OUTPUT_HORIZONTAL_PADDING: float = 20   # pts
OUTPUT_VERTICAL_PADDING: float = 20     # pts

PAGE_NUMBER_MARGIN: float = 10          # pts
PAGE_NUMBER_FONTSIZE: float = 9.0
PAGE_NUMBER_FONT: str = 'Times-Roman'
PAGE_NUMBER_COLOR: Tuple[float, float, float] = (0.1, 0.1, 0.1)

Block = Tuple[float, float, float, float, str, int, int]
TOCEntry = List[int | str]
Line = Tuple[float, float]

# ----------------------------
# Layout helpers
# ----------------------------

def get_content_rect(page: Page) -> Rect:
    """Find content bounds."""
    rect = page.rect
    rects = [Rect(b[:4]) for b in page.get_text("blocks")]

    # include images
    for img in page.get_images(full=True):
        name = img[7]  # <-- image name, not xref
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

def add_page_number(page: Page, text: str) -> None:
    """Render page number in top-right corner of rotated landscape page."""

    char_width = 0.6 * PAGE_NUMBER_FONTSIZE
    text_len = max(len(text), 5)
    text_width = char_width * text_len
    text_height = PAGE_NUMBER_FONTSIZE

    # height becomes width after rotation
    x1 = page.rect.width - PAGE_NUMBER_MARGIN
    x0 = x1 - text_height - PAGE_NUMBER_MARGIN 
    
    y0 = PAGE_NUMBER_MARGIN
    y1 = y0 + text_width + PAGE_NUMBER_MARGIN

    rect = fitz.Rect(x0, y0, x1, y1)
     
    page.insert_textbox(
        rect,
        text,
        fontname=PAGE_NUMBER_FONT,
        fontsize=PAGE_NUMBER_FONTSIZE,
        color=PAGE_NUMBER_COLOR,
        rotate=TARGET_ROTATION,
        align=fitz.TEXT_ALIGN_LEFT
    )

# -------------------------
# Box merging algorithm
# -------------------------

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

# --------------------------
# Optimal split position
# --------------------------

def find_y_splits(page: Page, content_rect: Rect) -> list[tuple[float, float]]:
    """Find a split location between lines within ±CENTER_WINDOW_RATIO."""
    text = page.get_text("dict")
    drawings = page.get_drawings()
    
    # y_top, y_bot
    lines: List[Line]  = []
    glyphs: List[Line] = []

    for block in text["blocks"]: # pyright: ignore[reportArgumentType, reportCallIssue]
        if block["type"] == 0: # pyright: ignore[reportArgumentType]
            for line in block["lines"]: # pyright: ignore[reportArgumentType]
                lines.append((line["bbox"][1], line["bbox"][3])) # pyright: ignore[reportArgumentType]
        else:
            lines.append((block["bbox"][1], block["bbox"][3])) # pyright: ignore[reportArgumentType]
    
    for drawing in drawings:
        rect = cast(Rect, drawing['rect'])
        glyphs.append((rect.y0, rect.y1))

    # Fill entire width cut at specified height.
    target_height = (content_rect.width) * TARGET_ASPECT_RATIO[1] / TARGET_ASPECT_RATIO[0]
    merged_lines = merge_y_overlaps(lines, glyphs)

    # CASE: One split
    # In this case page only has zero / one line and is larger than the desired height,
    # so return the entire content_rect, and let the scaler scale at the end.
    if (content_rect.y0 +  target_height >= content_rect.y1) or len(merged_lines) <2 :
        return [(content_rect.y0, content_rect.y1)]
    
    # CASE: multiple splits
    split_points: List[tuple[float, float]] = []

    start_cursor = content_rect.y0
    split_cursor = start_cursor + target_height
    
    for (_, curr_bot), (next_top, next_bot) in zip(merged_lines, merged_lines[1:]):      
    
        found_split = False
        # Split if:
        if (# 1) the best split cuts the next box
            ((split_cursor > next_top) and (split_cursor < next_bot))

            # 2) the best split cuts the space between the end of this box and the start of the next
            or ((split_cursor > curr_bot) and (split_cursor < next_top))

            # 3) the best split cuts the space between the start of the next and the end of this box 
            # i.e. only when next_top < curr_bot
            or ((split_cursor > next_top) and (split_cursor < curr_bot))
        ): 
            found_split = True

        # CASE: No split
        if not found_split:
            continue
        
        # CASE: Found split
        # Always split at the end of the current box
        split_points.append((start_cursor, curr_bot))

        # update cursors
        start_cursor = next_top
        split_cursor = start_cursor + target_height
        
        # CASE: Last split
        if split_cursor > content_rect.y1:
            split_points.append((start_cursor, content_rect.y1))
            break
    
    # Fallback: 
    # somehow completely failed, just naively split the pages 
    if len(split_points) == 0:
        num_splits = math.ceil(content_rect.height / target_height)

        print("failed to find split")
        print(page.number)

        split_points = [
            (
                content_rect.y0 + i *target_height,
                min(content_rect.y0 + (i+1) *target_height, content_rect.y1)
            )
            for i in range(num_splits)
        ]

    return split_points

# ----------------------------
# Main processing
# ----------------------------

def process_pdf_landscape(src_path: str, dst_path: str) -> None:
    src: Document = fitz.open(src_path)
    dst: Document = fitz.open()

    orig_toc = src.get_toc()
    meta = src.metadata

    # Source page -> destination page
    page_map: Dict[int, int] = {}

    for page in src:
        page_number: int = cast(int, page.number)
        orig_page_no = page_number + 1

        content_rect = get_content_rect(page)
        split_points = find_y_splits(page, content_rect)
        
        page_map[orig_page_no] = len(dst) + 1

        clips = [
            fitz.Rect(content_rect.x0, split_y[0], content_rect.x1, split_y[1])
            for split_y in split_points
        ]

        # Arrange the output pages
        #
        # Note: Pages will be read in landscape rotated -90deg
        #
        for clip_idx, clip_rect in enumerate(clips):
            target_width = clip_rect.width
            target_height = target_width * TARGET_ASPECT_RATIO[1] / TARGET_ASPECT_RATIO[0]
            
            new_page = dst.new_page(
                width=target_height, 
                height=target_width
            )
            
            avail_height = target_height - 2*OUTPUT_VERTICAL_PADDING
            avail_width = target_width - 2*OUTPUT_HORIZONTAL_PADDING

            scale = min(
                avail_height / clip_rect.height,
                avail_width / clip_rect.width
            )

            # Top left justify
            x1_target = target_height - OUTPUT_VERTICAL_PADDING
            y1_target = target_width - OUTPUT_HORIZONTAL_PADDING
            x0_target = x1_target - scale * clip_rect.height
            y0_target = y1_target - scale * clip_rect.width

            target = Rect(
                x0_target,
                y0_target,
                x1_target,
                y1_target
            )   

            new_page.show_pdf_page(
                target, 
                src,
                page_number, 
                clip=clip_rect, 
                rotate=TARGET_ROTATION
            )

            num_to_char = lambda n : chr(ord('`')+n+1)
            dst_page_number = f"{orig_page_no}{num_to_char(clip_idx)}"
            add_page_number(new_page, dst_page_number)

    # Remap TOC
    new_toc: List[TOCEntry] = []
    for level, title, page_no in orig_toc:
        new_page_no = page_map.get(page_no, max(1, page_no * 2 - 1))
        new_toc.append([level, title, new_page_no])

    dst.set_toc(new_toc)

    if meta is not None:
        dst.set_metadata(meta)

    dst.save(dst_path)

def main(argv: List[str]) -> None:
    if len(argv) != 3:
        print("Usage: script.py input.pdf output.pdf")
        sys.exit(1)

    process_pdf_landscape(argv[1], argv[2])

if __name__ == "__main__":
    main(sys.argv)