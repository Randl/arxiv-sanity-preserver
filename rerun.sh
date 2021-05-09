./venv/bin/python fetch_papers.py --max-index 500000 --start-index 0 --wait-time 10 --results-per-iteration 500
./venv/bin/python download_pdfs.py
./venv/bin/python parse_pdf_to_text.py
./venv/bin/python thumb_pdf.py
./venv/bin/python analyze.py
./venv/bin/python buildsvm.py
./venv/bin/python make_cache.py
