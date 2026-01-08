from pathlib import Path
from pypdf import PdfReader, PdfWriter

source_path = Path(r"C:\Users\marcu\Dropbox\Marcus\study\Cambridge\II\Asymptotic Methods\Asymptotics book clive.pdf")

rotation_rule = lambda i: 90 if i % 2 == 1 else -90

reader = PdfReader(source_path)
writer = PdfWriter()

for i, page in enumerate(reader.pages):
	page.rotate(rotation_rule(i))
	writer.add_page(page)

output_path = source_path.with_name(source_path.stem + "_rotated.pdf")
writer.write(output_path)
