import sys
from typing import Dict, List, Optional, Tuple, cast

import fitz
from fitz import Page, Document, Rect

TOCEntry = List[int | str]

def double_to_single(
    src_path: str, 
    dst_path: str,

    title: str,
    author: Optional[str] = None,
    new_toc: Optional[List[TOCEntry]] = None, 
    debug_path = None
):
    src: Document = fitz.open(src_path)
    dst: Document = fitz.open()
    
    debug: Optional[Document] = fitz.open() if debug_path is not None else None

    meta = src.metadata
    for page in src:
        page_number: int = cast(int, page.number)
        orig_page_no = page_number + 1

        vertical_top_padding = 40
        vertical_bot_padding = 80
        horizontal_padding = 40

        target_width = (page.rect.width /2) - 2*horizontal_padding
        target_height = page.rect.height - vertical_top_padding - vertical_bot_padding
        
        clips = [
            # Left page
            Rect(
                horizontal_padding,
                vertical_top_padding,
                horizontal_padding + target_width,
                vertical_top_padding + target_height
            ),
            # Right page
            Rect(
                3* horizontal_padding + target_width,
                vertical_top_padding,
                page.rect.width - horizontal_padding,
                page.rect.height - vertical_bot_padding,
            )
        ]

        if debug is not None:
            new_page = debug.new_page(
                width = page.rect.width,
                height = page.rect.height
            )
            
            new_page.show_pdf_page(
                new_page.rect,
                src,
                page_number
            )

            for clip in clips:
                new_page.draw_rect(
                    clip,
                    color=(0,0,1),  #blue
                    width=0.5
                )
            
        for clip in clips:
            # Render the clipped page
            new_page = dst.new_page(
                width=target_width,
                height=target_height
            )

            new_page.show_pdf_page(
                new_page.rect,
                src,
                page_number,
                clip=clip,
            )
    
    #Remap TOC
    if new_toc is not None:
        dst.set_toc(new_toc)

    if meta is not None:
        meta["title"] = title
        meta["modDate"] = fitz.get_pdf_now()
        if author is not None:
            meta["author"] = author
        dst.set_metadata(meta)

    dst.save(dst_path)

    if debug is not None:
        debug.save(debug_path)

def main():

    src_path = r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Asymptotic Methods\Asymptotics book clive_rotated.pdf"
    dst_path = r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Asymptotic Methods\Asymptotics book clive_single_paged.pdf"
    debug_path = r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Asymptotic Methods\Asymptotics book clive_debug.pdf"
 
    double_to_single(
        src_path, 
        dst_path,
        
        "Part II - Asymptotic Methods",
        "Clive Wells (?)",
        [
            [1, '1 Fundamentals', 5],
            [2, '1.1 Definitions', 6],
            [2, '1.2 Basic Results on the Manipulation of Asymptotic Expansions', 13],
            [2, '1.3 Taylor\'s Theorem', 16],
            [2, '1.5 Olver\'s Paradox', 19],
            [2, '1.6 Stoke\'s Phenomenon', 22],
            [2, '1.7 THe Coefficients of a Poincaré Expansion', 23],
            [2, '1.9 Superasymptotics and Optimal Truncation', 24],
            [2, '1.10 Asymptotic Behaviour Along Rays in a Sector', 25],
            
            [1, '3 Integration by Parts', 28],
            [2, '3.1 Using Partial Integration', 28],
            [2, '3.2 Asymptotic Expansions of erf(z) and Dawson\'s Integral', 30],
            [2, '3.3 The Exponential, Sine and Cosine Integrals', 33],
            [2, '3.4 The Incomplete Gamma Function', 35],
            [2, '3.5 A Rapidly Oscillating Integrand', 37],
            [2, '3.8 An Airy Function Integral', 38],
            [2, '3.7 A General Iteration Formula for Integration by Parts', 40],
            
            [1, '4 Laplace Integrals', 44],
            [2, '4.1 Watson\'s Lemma', 44],
            [2, '4.2 Watson\'s Lemma Examples', 48],
            [2, '4.3 Stoke\'s Phenomenon Example', 50],
            [2, '4.4 Laplace\'s method', 54],
            [2, '4.5 Informal Rationale for the Direct Expansion Approach', 55],
            [2, '4.6 Stirling\'s Approximation', 59],
            [2, '4.7 Examples using Direct Expansion', 60],
            [2, '4.8 Minimal Error and Optimal Truncation for the Stieltjes Function', 64],
            [2, '4.9 A Proof of Laplace\'s Method from Watson\'s Lemma', 64],
            
            [1, '5 The Method of Stationary Phase', 68],
            [2, '5.1 The Riemann-Lebesgue Lemma', 68],
            [2, '5.2 An Example of the Use of the Riemann-Lebesgue Lemma', 72],
            [2, '5.3 Dominated Convergence and the Fubini-Tonelli Theorems', 75],
            [2, '5.5 Informal Rationale for the Method of Stationary Phase', 76],
            [2, '5.6 Stationary Phase Examples', 82],
            
            [1, '6 The Method of Steepest Descent', 88],
            [2, '6.1 The Behaviour of an Analytic Function Near a Critical Point', 88],
            [2, '6.2 Steepest Descent Calculations', 96],
            [2, '6.3 Asymptotic Properties of the Airy Functions, Ai(z) and Bi(z)', 105],
            [2, '6.4 Singularities of the Integrand', 112],
            [2, '6.5 Asymptotic Properties of the Bessel Function Jv(z)', 114],
            [2, '6.6 Debye\'s Asymptotic Expansion of the Hankel Functions', 117],
            [2, '6.7 A Pole at the Saddle Point', 122],

            [1, '8 Differential Equations', 125],
            [2, '8.1 The Liouville-Green Approach', 125],
            [2, '8.2 The Asymptotic Condition', 127],
            [2, '8.4 Application: An Adiabatic Invariant for a Pendulum', 128],
            [2, '8.5 Bessel\'s Equation', 129],
            [2, '8.6 Legendre Polynomials', 131],
            
            [1, '9 The WKBJ Method', 135],
            [2, '9.1 A Very Brief Introduction to Quantum Mechanics', 135],
            [2, '9.2 The Connection Formulae', 137],
            [2, '9.3 The Directionality of the Connection Formulae', 141],
            [2, '9.4 Using the WKBJ Method to Determine Energy Eigenvalues', 143],
            [2, '9.5 Spherically Symmetric Potentials: The Langer Correction', 160],
            [2, '9.6 Quantum Tunnelling', 164],
            [2, '9.7 Scattering by Spherically Symmetric Potentials', 165],
            [2, '9.8 Coulomb Scattering', 169],

            [1, 'Index', 174]
        ],
        debug_path
        )

if __name__ == "__main__":
    main()