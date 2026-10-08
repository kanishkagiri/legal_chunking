import fitz
import re
import os

def chunk_pdf(pdf_path, output_dir="."):
    # 1. Read PDF text
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()

    # Save the whole document WITH headers as requested
    whole_doc_with_headers_path = os.path.join(output_dir, "whole_document_with_headers.txt")
    with open(whole_doc_with_headers_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Saved whole document with headers to {whole_doc_with_headers_path}")

    # Remove headers from the text
    p1 = re.compile(r'\n?\d+\nTHE GAZETTE OF INDIA EXTRAORDINARY\n\[PART II[^\n]*\n')
    p2 = re.compile(r'\n?SEC\. 1\]\nTHE GAZETTE OF INDIA EXTRAORDINARY\n\d+\n')
    
    clean_text = p1.sub('\n', text)
    clean_text = p2.sub('\n', clean_text)

    # Save the whole document WITHOUT headers
    whole_doc_without_headers_path = os.path.join(output_dir, "whole_document_without_headers.txt")
    with open(whole_doc_without_headers_path, "w", encoding="utf-8") as f:
        f.write(clean_text)
    print(f"Saved whole document without headers to {whole_doc_without_headers_path}")

    # 2. Split text based on \nCHAPTER [IVX]+\n
    # Using a positive lookahead to keep the chapter heading as part of the chunk
    chunks = re.split(r'(?=\nCHAPTER\s+[IVX]+\n)', clean_text)

    # 3. Filter out empty chunks and the preliminary part
    chapter_chunks = []
    for chunk in chunks:
        if re.match(r'^\nCHAPTER\s+[IVX]+\n', chunk):
            chapter_chunks.append(chunk.strip())

    print(f"Found {len(chapter_chunks)} chapters.")

    # 4. Save each chapter to a separate text file
    for i, chunk in enumerate(chapter_chunks):
        chapter_num = i + 1
        output_file = os.path.join(output_dir, f"chunk_chapter_{chapter_num}.txt")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(chunk)
        print(f"Saved Chapter {chapter_num} to {output_file} ({len(chunk)} characters)")

if __name__ == "__main__":
    chunk_pdf("consumer_act_2019.pdf")
