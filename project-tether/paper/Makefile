SRC = main

all: $(SRC).pdf

$(SRC).pdf: $(SRC).tex references.bib
	tectonic $(SRC).tex

clean:
	rm -f *.aux *.log *.bbl *.blg *.out *.pdf *.fls *.fdb_latexmk *.synctex.gz

.PHONY: all clean
