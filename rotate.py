import sys
from typing import Dict, List, Optional, Tuple, cast

import fitz
from fitz import Page, Document, Rect

TOCEntry = List[int | str]

rotation_rule = lambda page: 90 if page % 2 == 0 else -90

def rotate(src_path, dst_path):
    src: Document = fitz.open(src_path)
    dst: Document = fitz.open()

    for page in src:
        page_number: int = cast(int, page.number)
        orig_page_no = page_number + 1

        target_width = page.rect.width
        target_height = page.rect.height

        # Swap width & height for rotations
        new_page = dst.new_page(
            width=target_height,
            height=target_width
        )

        # Render the clipped page
        new_page.show_pdf_page(
            new_page.rect,
            src,
            page_number,
            rotate=rotation_rule(page_number),
        )
    
    # Remap TOC
    # new_toc: List[TOCEntry] = []
    # for toc_level, toc_title, toc_page_no in orig_toc:
    #     toc_page_no = cast(int, toc_page_no)

    #     # if toc_offset is not None:
    #     #     toc_page_no = toc_page_no + toc_offset

    #     new_page_no = page_map.get(toc_page_no)

    #     if new_page_no is None:
    #         print(f"Missing Page No: {toc_page_no}")
    #     else:
    #         new_toc.append([toc_level, toc_title, new_page_no])

    # dst.set_toc(new_toc)

    # if meta is not None:
    #     meta["title"] = title
    #     meta["modDate"] = fitz.get_pdf_now()
    #     if author is not None:
    #         meta["author"] = author
    #     dst.set_metadata(meta)

    dst.save(dst_path)

def main():

    src_path = r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Asymptotic Methods\Asymptotics book clive.pdf"
    dst_path = r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Asymptotic Methods\Asymptotics book clive_rotated.pdf"

    rotate(src_path, dst_path)

if __name__ == "__main__":
    main()