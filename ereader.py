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
TARGET_ROTATION: int = 270              # degrees

HORIZONTAL_PADDING: float = 6.0         # pts
VERTICAL_PADDING: float = 6.0           # pts

OUTPUT_HORIZONTAL_PADDING: float = 20   # pts
OUTPUT_VERTICAL_PADDING: float = 20     # pts

PAGE_NUMBER_MARGIN: float = 10          # pts
PAGE_NUMBER_FONTSIZE: float = 9.0
PAGE_NUMBER_FONT: str = 'Times-Roman'
PAGE_NUMBER_COLOR: Tuple[float, float, float] = (0.1, 0.1, 0.1)

Block = Tuple[float, float, float, float, str, int, int]
Metadata = dict[str, str]
TOCEntry = List[int | str]
Line = Tuple[float, float]

# ----------------------------
# Layout helpers
# ----------------------------

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
    
    for (curr_top, curr_bot), (next_top, next_bot) in zip(merged_lines, merged_lines[1:]):      
        
        found_split = False
        # Split at the bottom of curr box if:
        if (# 1) the best split cuts this box (and not the next box)
            ((split_cursor >= curr_top) and (split_cursor <= curr_bot))

            # 2) the best split cuts the next box
            or ((split_cursor >= next_top) and (split_cursor <= next_bot))

            # 3) the best split cuts the space between the end of this box and the start of the next
            or ((split_cursor >= curr_bot) and (split_cursor <= next_top))

            # 4) the best split cuts the space between the start of the next and the end of this box 
            # i.e. only when next_top < curr_bot
            or ((split_cursor >= next_top) and (split_cursor <= curr_bot))
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
        
        # CASE: Last split early break
        if split_cursor >= content_rect.y1:
            break
    
    # Append the final section
    split_points.append((start_cursor, content_rect.y1))
    
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

def process_pdf_landscape(
    src_path: str, 
    dst_path: str,

    title: str,
    author: Optional[str] = None,
    manual_toc: Optional[List[TOCEntry]] = None,
    toc_offset: Optional[int] = None
) -> None:
    
    src: Document = fitz.open(src_path)
    dst: Document = fitz.open()
    
    orig_toc = cast( List[TOCEntry], src.get_toc() if not manual_toc else manual_toc)
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
        num_clips = len(clips)
        for clip_idx, clip_rect in enumerate(clips):
            # Compute target page size based on desired aspect ratio
            target_width  = clip_rect.width
            target_height = target_width * TARGET_ASPECT_RATIO[1] / TARGET_ASPECT_RATIO[0]

            new_page = dst.new_page(
                width=target_height,  # rotated page width
                height=target_width   # rotated page height
            )

            # Available area inside padding
            avail_width  = target_height - 2 * OUTPUT_VERTICAL_PADDING   # rotated width
            avail_height = target_width  - 2 * OUTPUT_HORIZONTAL_PADDING # rotated height

            # Scale clip_rect to fit snugly
            scale = min(
                avail_width  / clip_rect.height,  # note: height maps to rotated width
                avail_height / clip_rect.width    # note: width maps to rotated height
            )

            # Compute target rectangle (top-left aligned in rotated coordinates)
            x1_target = target_height - OUTPUT_VERTICAL_PADDING
            y1_target = target_width  - OUTPUT_HORIZONTAL_PADDING
            x0_target = x1_target - scale * clip_rect.height
            y0_target = y1_target - scale * clip_rect.width

            target = Rect(
                x0_target,
                y0_target,
                x1_target,
                y1_target
            )


            # Render the clipped page
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
    for toc_level, toc_title, toc_page_no in orig_toc:
        toc_page_no = cast(int, toc_page_no)

        if toc_offset is not None:
            toc_page_no = toc_page_no + toc_offset

        new_page_no = page_map.get(toc_page_no)

        if new_page_no is None:
            print(f"Missing Page No: {toc_page_no}")
        else:
            new_toc.append([toc_level, toc_title, new_page_no])

    dst.set_toc(new_toc)

    if meta is not None:
        meta["title"] = title
        meta["modDate"] = fitz.get_pdf_now()
        if author is not None:
            meta["author"] = author
        dst.set_metadata(meta)

    dst.save(dst_path)

def main(argv: List[str]) -> None:
    # if len(argv) != 3:
    #     print("Usage: script.py input.pdf output.pdf")
    #     sys.exit(1)

    # process_pdf_landscape(sys.argv[1], sys.argv[2], "test")

    jobs = [
        {
            'src': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Applications of Quantum Mechanics\Tong justaqm.pdf",
            'dst': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Kobo Lecture notes\Part II - Applications of Quantum Mechanics - Tong.pdf",
            'title': 'Part II - Applications of Quantum Mechanics',
            'author': 'David Tong',
            'toc': [
                [1, "0. Introduction", 1],

                [1, "1. Scattering Theory", 2],
                [2, "1.1 Scattering in One Dimension", 2],
                [3, "1.1.1 Reflection and Transmission Amplitudes", 3],
                [3, "1.1.2 Introducing the S-Matrix", 8],
                [3, "1.1.3 A Parity Basis for Scattering", 9],
                [3, "1.1.4 Bound States", 13],
                [3, "1.1.5 Resonances", 15],

                [2, "1.2 Scattering in Three Dimensions", 19],
                [3, "1.2.1 The Cross-Section", 19],
                [3, "1.2.2 The Scattering Amplitude", 22],
                [3, "1.2.3 Partial Waves", 24],
                [3, "1.2.4 The Optical Theorem", 27],
                [3, "1.2.5 An Example: A Hard Sphere and Spherical Bessel Functions", 29],
                [3, "1.2.6 Bound States", 32],
                [3, "1.2.7 Resonances", 36],

                [2, "1.3 The Lippmann-Schwinger Equation", 38],
                [3, "1.3.1 The Born Approximation", 43],
                [3, "1.3.2 The Yukawa Potential and the Coulomb Potential", 44],
                [3, "1.3.3 The Born Expansion", 46],

                [2, "1.4 Rutherford Scattering", 47],
                [3, "1.4.1 The Scattering Amplitude", 49],

                [1, "2. Approximation Methods", 51],
                [2, "2.1 The Variational Method", 51],
                [3, "2.1.1 An Upper Bound on the Ground State", 51],
                [3, "2.1.2 An Example: The Helium Atom", 54],
                [3, "2.1.3 Do Bound States Exist?", 58],
                [3, "2.1.4 An Upper Bound on Excited States", 63],

                [1, "3. Band Structure", 65],
                [2, "3.1 Electrons Moving in One Dimension", 65],
                [3, "3.1.1 The Tight-Binding Model", 65],
                [3, "3.1.2 Nearly Free Electrons", 71],
                [3, "3.1.3 The Floquet Matrix", 78],
                [3, "3.1.4 Bloch's Theorem in One Dimension", 80],

                [2, "3.2 Lattices", 85],
                [3, "3.2.1 Bravais Lattices", 85],
                [3, "3.2.2 The Reciprocal Lattice", 91],
                [3, "3.2.3 The Brillouin Zone", 94],

                [2, "3.3 Band Structure", 96],
                [3, "3.3.1 Bloch's Theorem", 97],
                [3, "3.3.2 Nearly Free Electrons in Three Dimensions", 99],
                [3, "3.3.3 Wannier Functions", 103],
                [3, "3.3.4 Tight-Binding in Three Dimensions", 104],
                [3, "3.3.5 Deriving the Tight-Binding Model", 105],

                [2, "3.4 Scattering Off a Lattice", 111],
                [3, "3.4.1 The Bragg Condition", 114],
                [3, "3.4.2 The Structure Factor", 115],
                [3, "3.4.3 The Debye-Waller Factor", 117],

                [1, "4. Electron Dynamics in Solids", 119],
                [2, "4.1 Fermi Surfaces", 119],
                [3, "4.1.1 Metals vs Insulators", 120],
                [3, "4.1.2 The Discovery of Band Structure", 125],
                [3, "4.1.3 Graphene", 126],

                [2, "4.2 Dynamics of Bloch Electrons", 130],
                [3, "4.2.1 Velocity", 131],
                [3, "4.2.2 The Effective Mass", 133],
                [3, "4.2.3 Semi-Classical Equation of Motion", 134],
                [3, "4.2.4 Holes", 136],
                [3, "4.2.5 Drude Model Again", 138],

                [2, "4.3 Bloch Electrons in a Magnetic Field", 140],
                [3, "4.3.1 Semi-Classical Motion", 140],
                [3, "4.3.2 Cyclotron Frequency", 142],
                [3, "4.3.3 Onsager-Bohr-Sommerfeld Quantisation", 143],
                [3, "4.3.4 Quantum Oscillations", 145],

                [1, "5. Phonons", 148],
                [2, "5.1 Lattices in One Dimension", 148],
                [3, "5.1.1 A Monatomic Chain", 148],
                [3, "5.1.2 A Diatomic Chain", 150],
                [3, "5.1.3 Peierls Transition", 152],
                [3, "5.1.4 Quantum Vibrations", 155],
                [3, "5.1.5 The Mössbauer Effect", 159],

                [2, "5.2 From Atoms to Fields", 162],
                [3, "5.2.1 Phonons in Three Dimensions", 162],
                [3, "5.2.2 From Fields to Phonons", 164],

                [1, "6. Particles in a Magnetic Field", 166],
                [2, "6.1 Gauge Fields", 166],
                [3, "6.1.1 The Hamiltonian", 167],
                [3, "6.1.2 Gauge Transformations", 168],

                [2, "6.2 Landau Levels", 169],
                [3, "6.2.1 Degeneracy", 171],
                [3, "6.2.2 Symmetric Gauge", 173],
                [3, "6.2.3 An Invitation to the Quantum Hall Effect", 174],

                [2, "6.3 The Aharonov-Bohm Effect", 177],
                [3, "6.3.1 Particles Moving around a Flux Tube", 177],
                [3, "6.3.2 Aharonov-Bohm Scattering", 179],

                [2, "6.4 Magnetic Monopoles", 180],
                [3, "6.4.1 Dirac Quantisation", 180],
                [3, "6.4.2 A Patchwork of Gauge Fields", 183],
                [3, "6.4.3 Monopoles and Angular Momentum", 184],

                [2, "6.5 Spin in a Magnetic Field", 186],
                [3, "6.5.1 Spin Precession", 188],
                [3, "6.5.2 A First Look at the Zeeman Effect", 189],
            ],
            'toc_offset': 6
        }, 
        {
            'src': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Classical Dynamics\Classical Dynamics - Tong.pdf",
            'dst': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Kobo Lecture notes\Part II - Classical Dynamics - Tong.pdf",
            'title': 'Part II - Classical Dynamics',
            'author': 'David Tong',
            'toc': [
                [1, "1. Newton’s Laws of Motion", 1],
                [2, "1.1 Introduction", 1],
                [2, "1.2 Newtonian Mechanics: A Single Particle", 2],
                [3, "1.2.1 Angular Momentum", 3],
                [3, "1.2.2 Conservation Laws", 4],
                [3, "1.2.3 Energy", 4],
                [3, "1.2.4 Examples", 5],
                [2, "1.3 Newtonian Mechanics: Many Particles", 5],
                [3, "1.3.1 Momentum Revisited", 6],
                [3, "1.3.2 Energy Revisited", 8],
                [3, "1.3.3 An Example", 9],

                [1, "2. The Lagrangian Formalism", 10],
                [2, "2.1 The Principle of Least Action", 10],
                [2, "2.2 Changing Coordinate Systems", 13],
                [3, "2.2.1 Example: Rotating Coordinate Systems", 14],
                [3, "2.2.2 Example: Hyperbolic Coordinates", 16],
                [2, "2.3 Constraints and Generalised Coordinates", 17],
                [3, "2.3.1 Holonomic Constraints", 18],
                [3, "2.3.2 Non-Holonomic Constraints", 20],
                [3, "2.3.3 Summary", 21],
                [3, "2.3.4 Joseph-Louis Lagrange (1736-1813)", 22],
                [2, "2.4 Noether’s Theorem and Symmetries", 23],
                [3, "2.4.1 Noether’s Theorem", 24],
                [2, "2.5 Applications", 26],
                [3, "2.5.1 Bead on a Rotating Hoop", 26],
                [3, "2.5.2 Double Pendulum", 28],
                [3, "2.5.3 Spherical Pendulum", 29],
                [3, "2.5.4 Two Body Problem", 31],
                [3, "2.5.5 Restricted Three Body Problem", 33],
                [3, "2.5.6 Purely Kinetic Lagrangians", 36],
                [3, "2.5.7 Particles in Electromagnetic Fields", 36],
                [2, "2.6 Small Oscillations and Stability", 38],
                [3, "2.6.1 Example: The Double Pendulum", 41],
                [3, "2.6.2 Example: The Linear Triatomic Molecule", 42],

                [1, "3. The Motion of Rigid Bodies", 45],
                [2, "3.1 Kinematics", 46],
                [3, "3.1.1 Angular Velocity", 47],
                [3, "3.1.2 Path Ordered Exponentials", 49],
                [2, "3.2 The Inertia Tensor", 50],
                [3, "3.2.1 Parallel Axis Theorem", 52],
                [3, "3.2.2 Angular Momentum", 53],
                [2, "3.3 Euler’s Equations", 53],
                [3, "3.3.1 Euler’s Equations", 54],
                [2, "3.4 Free Tops", 55],
                [3, "3.4.1 The Symmetric Top", 55],
                [3, "3.4.2 Example: The Earth’s Wobble", 57],
                [3, "3.4.3 The Asymmetric Top: Stability", 57],
                [3, "3.4.4 The Asymmetric Top: Poinsot Construction", 58],
                [2, "3.5 Euler’s Angles", 62],
                [3, "3.5.1 Leonhard Euler (1707-1783)", 64],
                [3, "3.5.2 Angular Velocity", 65],
                [3, "3.5.3 The Free Symmetric Top Revisited", 65],
                [2, "3.6 The Heavy Symmetric Top", 67],
                [3, "3.6.1 Letting the Top go", 70],
                [3, "3.6.2 Uniform Precession", 71],
                [3, "3.6.3 The Sleeping Top", 72],
                [3, "3.6.4 The Precession of the Equinox", 72],
                [2, "3.7 The Motion of Deformable Bodies", 74],
                [3, "3.7.1 Kinematics", 74],
                [3, "3.7.2 Dynamics", 77],

                [1, "4. The Hamiltonian Formalism", 80],
                [2, "4.1 Hamilton’s Equations", 80],
                [3, "4.1.1 The Legendre Transform", 82],
                [3, "4.1.2 Hamilton’s Equations", 83],
                [3, "4.1.3 Examples", 84],
                [3, "4.1.4 Some Conservation Laws", 86],
                [3, "4.1.5 The Principle of Least Action", 87],
                [3, "4.1.6 William Rowan Hamilton (1805-1865)", 88],
                [2, "4.2 Liouville’s Theorem", 88],
                [3, "4.2.1 Liouville’s Equation", 90],
                [3, "4.2.2 Time Independent Distributions", 91],
                [3, "4.2.3 Poincaré Recurrence Theorem", 92],
                [2, "4.3 Poisson Brackets", 93],
                [3, "4.3.1 An Example: Angular Momentum and Runge-Lenz", 95],
                [3, "4.3.2 An Example: Magnetic Monopoles", 96],
                [3, "4.3.3 An Example: The Motion of Vortices", 98],
                [2, "4.4 Canonical Transformations", 100],
                [3, "4.4.1 Infinitesimal Canonical Transformations", 102],
                [3, "4.4.2 Noether’s Theorem Revisited", 104],
                [3, "4.4.3 Generating Functions", 104],
                [2, "4.5 Action-Angle Variables", 105],
                [3, "4.5.1 The Simple Harmonic Oscillator", 105],
                [3, "4.5.2 Integrable Systems", 107],
                [3, "4.5.3 Action-Angle Variables for 1d Systems", 108],
                [3, "4.5.4 Action-Angle Variables for the Kepler Problem", 111],
                [2, "4.6 Adiabatic Invariants", 113],
                [3, "4.6.1 Adiabatic Invariants and Liouville’s Theorem", 116],
                [3, "4.6.2 An Application: A Particle in a Magnetic Field", 116],
                [3, "4.6.3 Hannay’s Angle", 118],
                [2, "4.7 The Hamilton-Jacobi Equation", 121],
                [3, "4.7.1 Action and Angles from Hamilton-Jacobi", 124],
                [2, "4.8 Quantum Mechanics", 126],
                [3, "4.8.1 Hamilton, Jacobi, Schrödinger and Feynman", 128],
                [3, "4.8.2 Nambu Brackets", 131],
            ],
            'toc_offset': 6
        }, 
        {
            'src': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Dynamical Systems\Peter Haynes Dyn Sys.pdf",
            'dst': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Kobo Lecture notes\Part II - Dynamical Systems - Haynes.pdf",
            'title': 'Part II - Dynamical Systems',
            'author': 'Peter Haynes',
            'toc': [
                [1, "Part II Dynamical Systems Michaelmas Term 2014", 1],

                [2, "Informal Introduction", 1],
                [2, "Course Structure", 1],
                [2, "Books", 1],
                [2, "Motivation", 3],

                [1, "1 Introduction and Basic Definitions", 7],
                [2, "1.1 Elementary concepts", 7],
                [2, "1.2 Initial Value Problems", 7],
                [2, "1.3 Trajectories and Flows", 8],
                [2, "1.4 Invariant and Limit Sets", 9],
                [2, "1.5 Topological equivalence and structural stability", 11],

                [1, "2 Flows in R^2", 13],
                [2, "2.1 Linearization", 13],
                [2, "2.2 Classification of fixed points", 13],
                [2, "2.3 Effect of nonlinear terms", 15],
                [3, "2.3.1 Stable and Unstable Manifolds", 15],
                [3, "2.3.2 Nonlinear terms for non-hyperbolic cases", 17],
                [2, "2.4 Sketching phase portraits", 19],

                [1, "3 Stability", 21],
                [2, "3.1 Definitions of stability", 21],
                [2, "3.2 Lyapunov functions", 23],
                [2, "3.3 Bounding functions", 26],

                [1, "4 Existence and stability of periodic orbits in R^2", 28],
                [2, "4.1 The Poincaré Index", 28],
                [2, "4.2 Poincaré-Bendixson Theorem", 30],
                [2, "4.3 Dulac's criterion and the divergence test", 32],
                [2, "4.4 Near-Hamiltonian flows", 33],
                [2, "4.5 Stability of Periodic Orbits", 36],
                [3, "4.5.1 Floquent multipliers and Lyapnunov exponents", 36],
                [2, "4.6 Example - the Van der Pol oscillator", 37],

                [1, "5 Bifurcations", 43],
                [2, "5.1 Introduction", 43],
                [2, "5.2 Stationary bifurcations in R^2", 43],
                [3, "5.2.1 One-dimensional bifurcations", 43],
                [3, "5.2.2 Bifurcations in R^2", 47],
                [2, "5.3 The Centre Manifold", 47],
                [2, "5.4 Oscillatory/Hopf Bifurcations in R^2", 50],
                [2, "5.5 *Bifurcations on periodic orbits*", 52],

                [1, "6 Bifurcations in Maps", 53],
                [2, "6.1 Examples of maps", 53],
                [2, "6.2 Fixed points, cycles and stability", 56],
                [2, "6.3 Local bifurcations in 1-dimensional maps", 56],

                [1, "7 Chaos", 59],
                [2, "7.1 Introduction", 59],
                [2, "7.2 The Sawtooth Map (Bernoulli shift)", 60],
                [2, "7.3 Horseshoes, symbolic dynamics and the shift map", 61],
                [2, "7.4 Period 3 implies chaos", 62],
                [2, "7.5 Existence of N-cycles", 62],
                [2, "7.6 The Tent Map", 65],
                [2, "7.7 Unimodal Maps", 68],
                [3, "7.7.1 The Logistic Map", 68],
                [3, "7.7.2 General Properties of Unimodal Maps", 68],
                [3, "7.7.3 Scaling Invariance and Feigenbaum's Constant", 72],
            ],
           'toc_offset': None
        },
        {
            'src': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Electrodynamics\Electrodynamics - Challinor.pdf",
            'dst': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Kobo Lecture notes\Part II - Electrodynamics - Challinor.pdf",
            'title': 'Part II - Electrodynamics',
            'author': 'Anthony Challinor',
            'toc': [
                [1, "Electrodynamics", 1],
                [2, "1 Introduction", 1],

                [1, "Part I  Electromagnetism as a classical field theory", 2],
                [2, "2 Review of Maxwell’s equations in relativistic form", 2],

                [2, "3 Action principles for electrodynamics", 6],
                [3, "3.1 Relativistic point particles in external fields", 7],
                [4, "3.1.1 Motion of charged particles in constant, uniform fields", 10],
                [3, "3.2 Action principle for the electromagnetic field", 15],
                [4, "3.2.1 Action principle with a prescribed current", 15],
                [4, "3.2.2 Full action for classical electrodynamics (non-examinable)", 16],

                [2, "4 Energy and momentum of the electromagnetic field", 18],
                [3, "4.1 Energy and momentum conservation", 18],
                [3, "4.2 Stress-energy tensor", 20],
                [3, "4.3 Covariant conservation of the stress-energy tensor", 22],
                [3, "4.4 Stress-energy tensor and Noether’s theorem (non-examinable)", 23],
                [3, "4.5 Symmetry of the stress-energy tensor (non-examinable)", 25],
                [3, "4.6 Stress-energy tensor of a plane electromagnetic wave", 27],
                [4, "4.6.1 Radiation pressure of a photon “gas”", 30],

                [1, "Part II  Radiation of electromagnetic waves", 32],
                [2, "5 Retarded potentials of a time-dependent charge distribution", 32],

                [2, "6 Dipole Radiation", 35],
                [3, "6.1 Power radiated", 39],
                [3, "6.2 Beyond the electric-dipole approximation", 39],

                [2, "7 Scattering", 41],
                [3, "7.1 Thomson scattering", 42],
                [3, "7.2 Rayleigh scattering", 43],

                [2, "8 Radiation from an arbitrarily moving point charge", 44],
                [3, "8.1 Li´enard–Weichert potentials and fields", 44],
                [3, "8.2 Power radiated", 49],
                [3, "8.3 Synchrotron radiation (non-examinable)", 52],

                [1, "Part III  Electromagnetism in media", 54],
                
                [2, "9 Electromagnetic properties of matter", 54],
                [3, "9.1 Dielectric media", 54],
                [3, "9.2 Magnetic media", 56],
                
                [2, "10 Macroscopic Maxwell equations", 58],
                [3, "10.1 Averaging the microscopic Maxwell equations", 58],

                [2, "11 Electromagnetic waves in simple dielectric media", 68],
                [3, "11.1 Reflection and refraction", 70],
                [3, "11.2.1 Normal polarization", 71],
                [3, "11.2.2 Parallel polarization", 73],
                [3, "11.2.3 Brewster's angle", 75],
                [3, "11.2.4 Total internal reflection", 76],

                [1, "12 Dispersion", 77],
                [2, "12.1 Atomic polarizability revisited: a simple model for ε", 77],
                [2, "12.2 Electromagnetic waves in dispersive media", 78],
                [3, "12.2.1 Phase and group velocity", 79],
                [2, "12.2 Electromagnetic waves in dispersive media", 78],
                [3, "12.2.1 Phase and group velocity", 80],

                [2, "12.3 Causality and the Kramers–Kronig relations", 82],
                [3, "12.3.1 Kramers–Kronig relations", 84],

                [1, "13 Electromagnetic waves in conductors", 85],
                [2, "13.1 Drude model", 85],
                [2, "13.2 Propagation of waves in conductors", 87],
                [3, "13.2.1 Low-frequency behaviour", 89],
                [3, "13.2.2 High-frequency behaviour", 90],
                [3, "13.2.3 Plasma oscillations", 91],

                [1, "Appendix A  Review of special relativity", 92],
                [2, "A.1 Lorentz transformations", 92],
                [2, "A.2 4-Vectors", 94],
                [3, "A.2.1 Examples of 4-vectors in relativistic kinematics", 98],
                [2, "A.3 4-Tensors", 100],
            ],
           'toc_offset': None
        },
        {
            'src': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\General Relativity\General Relativity - Sperhake.pdf",
            'dst': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Kobo Lecture notes\Part II - General Relativity - Sperhake.pdf",
            'title': 'Part II - General Relativity',
            'author': 'Ulrich Sperhake',
            'toc': None,
            'toc_offset': None
        },
        {
            'src': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Integrable Systems\Dunajski ISlecture_notes_2012.pdf",
            'dst': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Kobo Lecture notes\Part II - Integrable Systems - Dunajski.pdf",
            'title': 'Part II - Integrable Systems',
            'author': 'Maciej Dunajski',
            'toc': [
                [1, "1 Integrability in classical mechanics", 4],
                [2, "1.1 Hamiltonian formalism", 4],
                [2, "1.2 Integrability and action–angle variables", 7],
                [2, "1.3 Poisson structures", 15],

                [1, "2 Soliton equations and Inverse Scattering Transform", 20],
                [2, "2.1 History of two examples", 20],
                [3, "2.1.1 Physical derivation of KdV", 21],
                [3, "2.1.2 Bäcklund transformations for the Sine–Gordon equation", 24],
                [2, "2.2 Inverse scattering transform for KdV", 25],
                [3, "2.2.1 Direct scattering", 27],
                [3, "2.2.2 Properties of the scattering data", 29],
                [3, "2.2.3 Inverse Scattering", 30],
                [3, "2.2.4 Lax formulation", 31],
                [3, "2.2.5 Evolution of the scattering data", 32],
                [2, "2.3 Reflectionless potentials and solitons", 33],
                [3, "2.3.1 One soliton solution", 33],
                [3, "2.3.2 N–soliton solution", 34],
                [3, "2.3.3 Two-soliton asymptotics", 35],

                [1, "3 Hamiltonian formalism and the zero curvature representation", 39],
                [2, "3.1 First integrals", 39],
                [2, "3.2 Hamiltonian formalism", 41],
                [3, "3.2.1 Bi–Hamiltonian systems", 42],
                [2, "3.3 Zero curvature representation", 44],
                [3, "3.3.1 The Riemann–Hilbert problem", 45],
                [3, "3.3.2 Dressing method", 46],
                [3, "3.3.3 From Lax representation to zero curvature", 49],
                [2, "3.4 Hierarchies and finite gap solutions", 51],

                [1, "4 Lie symmetries and reductions", 54],
                [2, "4.1 Lie groups and Lie algebras", 54],
                [2, "4.2 Vector fields and one parameter groups of transformations", 57],
                [2, "4.3 Symmetries of differential equations", 60],
                [3, "4.3.1 How to find symmetries", 63],
                [3, "4.3.2 Prolongation formula", 63],
                [2, "4.4 Painlevé equations", 66],
                [3, "4.4.1 Painlevé test", 70],

                [1, "A Manifolds", 72],
            ],
           'toc_offset': 1
        },
        {
            'src': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Principles of Quantum Mechanics\Principles of Quantum Mechanics - Skinner.pdf",
            'dst': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Kobo Lecture notes\Part II - Principles of Quantum Mechanics - Skinner.pdf",
            'title': 'Part II - Principles of Quantum Mechanics',
            'author': 'David Skinner',
            'toc': [
            [1, "1 Introduction", 8],

            [1, "2 Hilbert Space", 11],
            [2, "2.1 Definition of Hilbert Space", 11],
            [3, "2.1.1 Examples", 12],
            [3, "2.1.2 Dual Spaces", 14],
            [3, "2.1.3 Dirac Notation and Continuum States", 15],
            [2, "2.2 Operators", 17],
            [2, "2.3 Composite Systems", 21],
            [3, "2.3.1 Tensor Product of Hilbert Spaces", 21],
            [2, "2.4 Postulates of Quantum Mechanics", 25],
            [3, "2.4.1 The Generalized Uncertainty Principle", 28],

            [1, "3 The Harmonic Oscillator", 29],
            [2, "3.1 Raising and Lowering Operators", 29],
            [2, "3.2 Dynamics of Oscillators", 32],
            [3, "3.2.1 Anharmonic Oscillations", 34],

            [1, "4 Transformations and Symmetries", 37],
            [2, "4.1 Transformations of States and Operators", 37],
            [3, "4.1.1 Continuous Transformations", 39],
            [2, "4.2 Translations", 40],
            [2, "4.3 Rotations", 44],
            [3, "4.3.1 Translations Around a Circle", 48],
            [3, "4.3.2 Spin", 49],
            [2, "4.4 Time Translations", 51],
            [3, "4.4.1 The Heisenberg Picture", 52],
            [2, "4.5 Dynamics", 53],
            [3, "4.5.1 Symmetries and Conservation Laws", 56],
            [2, "4.6 Parity", 57],

            [1, "5 Angular Momentum", 61],
            [2, "5.1 Angular Momentum Eigenstates (A Little Representation Theory)", 62],
            [2, "5.2 Rotations and Orientation", 64],
            [3, "5.2.1 Rotation of Diatomic Molecules", 65],
            [2, "5.3 Spin", 67],
            [3, "5.3.1 Large Rotations", 67],
            [3, "5.3.2 The Stern–Gerlach Experiment", 68],
            [3, "5.3.3 Spinors and Projective Representations", 70],
            [3, "5.3.4 Spin Matrices", 73],
            [3, "5.3.5 Paramagnetic Resonance and MRI Scanners", 76],
            [2, "5.4 Orbital Angular Momentum", 79],
            [3, "5.4.1 Spherical Harmonics", 79],
            [3, "5.4.2 The Momentum Representation", 80],

            [1, "6 Addition of Angular Momentum", 83],
            [2, "6.1 Combining the Angular Momenta of Two States", 84],
            [3, "6.1.1 j ⊗ 0 = j", 88],
            [3, "6.1.2 1/2 ⊗ 1/2 = 1 ⊕ 0", 88],
            [3, "6.1.3 1 ⊗ 1/2 = 3/2 ⊕ 1/2", 89],
            [3, "6.1.4 The Classical Limit", 90],
            [2, "6.2 Angular Momentum of Operators", 91],
            [3, "6.2.1 The Wigner–Eckart Theorem", 91],
            [3, "6.2.2 Dipole Moment Transitions", 91],

            [1, "7 Identical Particles", 102],
            [2, "7.1 Bosons and Fermions", 102],
            [3, "7.1.1 Pauli’s Exclusion Principle", 104],
            [3, "7.1.2 The Periodic Table", 105],
            [3, "7.1.3 White Dwarfs, Neutron Stars and Supernovae", 109],
            [2, "7.2 Exchange and Parity in the Centre of Momentum Frame", 109],
            [3, "7.2.1 Identical Particles and Inelastic Collisions", 109],

            [1, "8 Perturbation Theory I: Time Independent Case", 112],
            [2, "8.1 An Analytic Expansion", 112],
            [3, "8.1.1 Fine Structure of Hydrogen", 115],
            [3, "8.1.2 Hyperfine Structure of Hydrogen", 119],
            [3, "8.1.3 The Ground State of Helium", 120],
            [3, "8.1.4 The Quadratic Stark Effect", 123],
            [2, "8.2 Degenerate Perturbation Theory", 125],
            [3, "8.2.1 The Linear Stark Effect", 128],
            [2, "8.3 Does Perturbation Theory Converge?", 129],

            [1, "9 Perturbation Theory II: Time Dependent Case", 132],
            [2, "9.1 The Interaction Picture", 132],
            [2, "9.2 Prodding the Harmonic Oscillator", 135],
            [2, "9.3 A Constant Perturbation Turned On at t = 0", 136],
            [2, "9.4 Fermi’s Golden Rule", 137],
            [3, "9.4.1 The Photoelectric Effect", 139],
            [3, "9.4.2 Absorption and Stimulated Emission", 142],
            [3, "9.4.3 Spontaneous Emission", 144],

            [1, "10 Interpreting Quantum Mechanics", 148],
            [2, "10.1 The Density Operator", 148],
            [3, "10.1.1 The Bloch Sphere", 150],
            [2, "10.2 Entropy", 151],
            [3, "10.2.1 The Gibbs Distribution", 153],
            [2, "10.3 Reduced Density Operators", 153],
            [2, "10.4 Decoherence", 154],
            [2, "10.5 Time Evolution of Density Operators and Reduced Density Operators", 155],
            [3, "10.5.1 Decoherence and Measurement", 157],
            [2, "10.6 Quantum Mechanics or Hidden Variables?", 159],
            [3, "10.6.1 Bell’s Inequality", 161],
            [3, "10.6.2 The CHSH Inequality", 163],
        ],
            'toc_offset': None
        },
        {
            'src': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Quantum Information and Computation\Quantum Information and Computation - Josza.pdf",
            'dst': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Kobo Lecture notes\Part II - Quantum Information and Computation - Josza.pdf",
            'title': 'Part II - Quantum Information and Computation',
            'author': 'Richard Jozsa',
            'toc': [
                [1, "1 Introduction: why quantum computation and information?", 3],

                [1, "2 Principles of quantum mechanics and the Dirac bra-ket notation", 7],
                [2, "2.1 Quantum states and operations", 7],
                [2, "2.2 Quantum measurements", 13],
                [2, "2.3 Some basic unitary operations for qubits", 18],
                [2, "2.4 An aside: superposition and quantum interference", 20],

                [1, "3 Quantum states as information carriers", 23],
                [2, "3.1 The no cloning theorem", 24],
                [2, "3.2 Distinguishing non-orthogonal states", 27],
                [2, "3.3 The no-signalling principle", 30],
                [2, "3.4 Quantum dense coding", 34],

                [1, "4 Quantum teleportation", 35],

                [1, "5 Quantum cryptography: BB84 quantum key distribution", 39],

                [1, "6 Basics of classical computation and complexity", 47],
                [2, "6.1 Query complexity and promise problems", 50],

                [1, "7 Circuit model of quantum computation", 51],

                [1, "8 The Deutsch–Jozsa algorithm", 55],
                [2, "8.1 Simon's algorithm", 59],

                [1, "9 Quantum Fourier transform and periodicities", 60],
                [2, "9.1 QFT mod N", 60],
                [2, "9.2 Periodicity determination", 61],
                [2, "9.3 Efficient implementation of QFT", 64],

                [1, "10 Quantum algorithms for search problems", 68],
                [2, "10.1 The class NP and search problems", 68],
                [2, "10.2 Grover's quantum searching algorithm", 71],

                [1, "11 Shor's quantum factoring algorithm", 78],
                [2, "11.1 Factoring as a periodicity problem", 78],
                [2, "11.2 Computing the period r of f(k) = a^k mod N", 80],
                [2, "11.3 Getting r from a good c value", 83],
                [2, "11.4 Assessing the complexity of Shor's algorithm", 87],
            ],
           'toc_offset': None
        },
        {
            'src': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Statisical Modelling\Statistical Modelling - Zhao Qing Yuan.pdf",
            'dst': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Kobo Lecture notes\Part II - Statistical Modelling - Zhao.pdf",
            'title': 'Part II - Statistical Modelling',
            'author': 'Zhao Qing Yuan',
            'toc': None,
            'toc_offset': None
        },
        {
            'src': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Statistical Physics\Statistical Physics - Sperhake.pdf",
            'dst': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Kobo Lecture notes\Part II - Statistical Physics - Sperhake.pdf",
            'title': 'Part II - Statistical Physics',
            'author': 'Ulrich Sperhake',
            'toc': [
                [1, "A The fundamentals of statistical physics", 4],
                [2, "A.1 Introduction", 4],
                [2, "A.2 The microcanonical ensemble", 4],
                [3, "A.2.1 Entropy and the 2nd law of thermodynamics", 5],
                [3, "A.2.2 Temperature", 7],
                [3, "A.2.3 The Two-State system", 9],
                [3, "A.2.4 Pressure, Volume, 1st law of thermodynamics", 12],
                [2, "A.3 The canonical ensemble", 13],
                [3, "A.3.1 The partition function", 14],
                [3, "A.3.2 Entropy", 16],
                [3, "A.3.3 Free energy", 19],
                [2, "A.4 The grand canonical ensemble", 20],
                [3, "A.4.1 The chemical potential", 20],
                [3, "A.4.2 The grand canonical ensemble", 21],
                [3, "A.4.3 The grand canonical potential", 21],

                [1, "B Classical Gases", 23],
                [2, "B.1 From QM to classical", 23],
                [2, "B.2 Ideal gas", 24],
                [3, "B.2.1 Equipartition of energy", 25],
                [3, "B.2.2 Entropy", 26],
                [3, "B.2.3 The ideal gas in the GrCE", 27],
                [2, "B.3 Maxwell distribution", 28],
                [2, "B.4 Diatomic gas", 30],
                [2, "B.5 Interacting gas", 31],
                [3, "B.5.1 Mayer f function and B₂", 32],
                [3, "B.5.2 Van der Waals equation of state", 34],

                [1, "C Quantum Gases", 36],
                [2, "C.1 Density of states", 36],
                [3, "C.1.1 Relativistic systems", 37],
                [2, "C.2 Photons: Blackbody Radiation", 37],
                [3, "C.2.1 Planck distribution", 38],
                [3, "C.2.2 Cosmic Microwave Background (CMB)", 40],
                [3, "C.2.3 The birth of QM", 40],
                [2, "C.3 Phonons", 41],
                [2, "C.4 The diatomic gas revisited", 43],
                [2, "C.5 Bosons", 44],
                [3, "C.5.1 Bose–Einstein (BE) distribution", 44],
                [3, "C.5.2 QM gas at high T", 46],
                [3, "C.5.3 Bose–Einstein condensation", 47],
                [3, "C.5.4 Heat capacity: A first look at phase transitions", 49],
                [2, "C.6 Fermions", 52],
                [3, "C.6.1 Ideal Fermi gas", 52],
                [3, "C.6.2 Degenerate Fermi gas and the Fermi surface", 53],
                [3, "C.6.3 Fermi gas at low T", 54],
                [3, "C.6.4 White Dwarfs and the Chandrasekhar limit", 56],
                [3, "C.6.5 Pauli paramagnetism (not lectured)", 57],

                [1, "D Classical Thermodynamics", 59],
                [2, "D.1 Temperature and the 0th law", 59],
                [2, "D.2 The 1st law", 60],
                [2, "D.3 The 2nd law", 61],
                [3, "D.3.1 The Carnot cycle", 62],
                [3, "D.3.2 Thermodynamic temperature scale and ideal gas", 63],
                [3, "D.3.3 Entropy", 65],
                [2, "D.4 Thermodynamic potentials: Free Energy, Enthalpy", 67],
                [3, "D.4.1 Maxwell’s relations", 68],
                [2, "D.5 The 3rd law", 69],

                [1, "E Phase transitions", 70],
                [2, "E.1 Liquid-gas transition", 70],
                [3, "E.1.1 Phase equilibrium", 70],
                [3, "E.1.2 The Clausius–Clapeyron Equation", 72],
                [3, "E.1.3 The critical point", 73],
                [2, "E.2 The Ising model", 75],
                [3, "E.2.1 Mean-field theory", 76],
                [3, "E.2.2 Critical exponents", 78],
                [2, "E.3 Landau Theory", 81],
                [3, "E.3.1 Second order phase transitions", 81],
                [3, "E.3.2 First order phase transitions", 82],
           ],
           'toc_offset': None
        }
    ]
    
    for job in jobs:
        print(f"Working on {job['title']}")
        process_pdf_landscape(
            job['src'], 
            job['dst'],
            job['title'],
            job['author'],
            job['toc'],
            job['toc_offset']
        )

if __name__ == "__main__":
    main(sys.argv)