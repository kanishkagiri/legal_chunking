# Set up LegalGuard on another computer

This repository uses Python scripts for parsing and retrieval, a Neo4j database for the Act graph and indexes, and two locally cached models for embeddings and reranking. `requirements-embeddings.txt` installs the Python packages; it does not install Python itself, create/configure Neo4j, provide the graph data, or download the model files in advance.

## Requirements

- Python 3.10 or newer. Python 3.11 is a suitable choice.
- Git, if getting the project by cloning the repository.
- Network access for Python package installation, the first model downloads, and access to the Neo4j database.
- Access to a Neo4j database that already contains this project’s Consumer Protection Act graph and indexes, or permission to import the data into a separate database you control.
- The repository data files, including `chunk_chapter_1.txt` through `chunk_chapter_8.txt`. For graph import, the Act PDF is also needed if regenerating chapter text with `chunk_pdf.py`.

## 1. Get the project files

Clone the project, or copy the complete project directory. Make sure the chapter text files are included. The generated `parsed_output/` files are useful for review and avoid having to regenerate reports, but the parser can recreate them from the chapter text files.

Do not copy a developer’s `.env` file into source control or share it in a public archive. It contains database credentials and is intentionally ignored by Git.

## 2. Create a virtual environment and install packages

### Windows PowerShell

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-embeddings.txt
```

If PowerShell blocks virtual-environment activation, either use the activation instructions for the installed Python distribution or invoke `.venv\Scripts\python.exe` directly in the commands below.

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-embeddings.txt
```

`PyMuPDF` is included for the optional PDF-to-chapter-text script. The retrieval and graph scripts use `fastembed`, the Neo4j Python driver, and `python-dotenv`.

## 3. Configure Neo4j access

Copy `.env.example` to `.env` and replace the three example values with credentials for the database you are authorized to use:

```text
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USERNAME=your-neo4j-username
NEO4J_PASSWORD=your-password
```

In Windows PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
```

In macOS or Linux:

```bash
cp .env.example .env
nano .env
```

Use a database that already has the LegalGuard Act nodes, relationships, full-text index `act_text_lookup`, and vector index `act_vector_index`. Having valid credentials alone is not enough if the target database is empty or lacks these indexes. The current graph can be shared among collaborators if the database owner provisions each person’s access; otherwise, use a separate database and follow the import steps below.

Never put the `.env` values in a command pasted into chat, a checked-in file, or a frontend configuration. Keep `.env` private; it is listed in `.gitignore`.

## 4. Run retrieval

From the project directory, use one of the three supported modes:

```powershell
python rag_backend.py "What can the Central Authority do about a misleading advertisement?" --mode keyword --top-k 5
python rag_backend.py "What can the Central Authority do about a misleading advertisement?" --mode vector --top-k 5
python rag_backend.py "What can the Central Authority do about a misleading advertisement?" --mode graph --top-k 5
```

On macOS or Linux, use the same commands with `python3` if `python` does not point to the virtual environment. The first vector/reranker run downloads the configured models into `.model_cache/`; allow extra time and disk space. Later runs reuse those local files. The current backend returns reranked evidence and stops before SLM answer generation; it does not start a chat web server or frontend.

To evaluate one question against known relevant provisions for all three modes:

```powershell
python evaluate_retrieval.py --question "What procedure applies when testing goods for a defect?" --gold "Section 38(2)" --gold "Section 38(5)"
```

See [RETRIEVAL_EVALUATION_GUIDE.md](RETRIEVAL_EVALUATION_GUIDE.md) for gold citation guidance, saving JSON output, and metric definitions.

## 5. Import into a separate Neo4j database (optional)

Skip this section when using the already populated project database. Import commands write to Neo4j. Use only a database you own or have explicit permission to modify, and do not point these commands at a shared production database without coordinating with its owner.

The chapter text files must be present. If they need to be regenerated from the PDF, install dependencies first and run:

```powershell
python chunk_pdf.py
```

Then parse and validate the chapters. This first command is a dry run and writes `parsed_output/act_sections.json` and validation reports locally:

```powershell
python neo4j_pipeline.py
```

If the validation output is correct, import the Act structure and full-text index:

```powershell
python neo4j_pipeline.py --import
```

Generate and import vector embeddings and the vector index:

```powershell
python embed_act.py
python embed_act.py --import
```

Generate the ontology report/edges, review them, then import ontology entities and relationships:

```powershell
python extract_ontology.py
python extract_ontology.py --import
```

The dry runs help inspect generated results before writes, but `--import` mutates the configured Neo4j database. Store embeddings and ontology data only after setting `.env` to the intended database. For a full description of nodes, relationships, and retrieval modes, see [LEGALGUARD_PROJECT_STATUS.md](LEGALGUARD_PROJECT_STATUS.md).

## Common setup issues

- **Missing `NEO4J_URI`, username, or password:** confirm `.env` is in the project root and contains the expected variable names.
- **Database connection/index errors:** credentials must have access to the selected database, and the required graph data and indexes must exist there.
- **Slow first retrieval or download errors:** embedding/reranking models download on first use; confirm network access and retry.
- **Import says chapter input is missing:** restore `chunk_chapter_*.txt` files or regenerate them from `consumer_act_2019.pdf` with `chunk_pdf.py`.
- **A module import fails:** activate the project virtual environment and rerun `python -m pip install -r requirements-embeddings.txt`.
