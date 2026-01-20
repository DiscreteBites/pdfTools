from typing import Dict, List, Optional, Tuple, cast

import fitz
from fitz import Page, Document, Rect

TOCEntry = List[int | str]

def set_toc(
    src_path: str, 
    dst_path: str,
    toc: List[TOCEntry], 
    toc_offset: Optional[int]
):
    src: Document = fitz.open(src_path)

    if toc_offset is not None:
        toc = [[level, title, int(page) + toc_offset] for level, title, page in toc]
    
    src.set_toc(toc)
    src.save(dst_path)

def main():
    jobs = [
    {
        'src': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Electrodynamics\Electrodynamics - Challinor.pdf",
        'dst': r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Electrodynamics\Electrodynamics - Challinor_wtoc.pdf",
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

            [2, "12 Dispersion", 77],
            [3, "12.1 Atomic polarizability revisited: a simple model for ε", 77],
            [3, "12.2 Electromagnetic waves in dispersive media", 78],
            [4, "12.2.1 Phase and group velocity", 79],
            [3, "12.2 Electromagnetic waves in dispersive media", 78],
            [4, "12.2.1 Phase and group velocity", 80],

            [3, "12.3 Causality and the Kramers–Kronig relations", 82],
            [4, "12.3.1 Kramers–Kronig relations", 84],

            [2, "13 Electromagnetic waves in conductors", 85],
            [3, "13.1 Drude model", 85],
            [3, "13.2 Propagation of waves in conductors", 87],
            [4, "13.2.1 Low-frequency behaviour", 89],
            [4, "13.2.2 High-frequency behaviour", 90],
            [4, "13.2.3 Plasma oscillations", 91],

            [1, "Appendix A  Review of special relativity", 92],
            [2, "A.1 Lorentz transformations", 92],
            [2, "A.2 4-Vectors", 94],
            [3, "A.2.1 Examples of 4-vectors in relativistic kinematics", 98],
            [2, "A.3 4-Tensors", 100],
        ],
        'toc_offset': 0
    },
]

    for job in jobs:
        print(f"Working on {job['src']}")
        set_toc(
            job['src'],
            job['dst'],
            job['toc'],
            job['toc_offset']
        )
    
if __name__ == "__main__":
    main()