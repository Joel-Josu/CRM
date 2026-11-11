# Data Desk — AI-powered analytics assistant

Data Desk is a local web app for asking questions about CSV, Excel (`.xlsx`), and JSON datasets. It calculates results from the uploaded rows, then presents a short explanation, searchable/sortable table, visualization, and calculation methodology.

## Run locally

The app uses only the Python standard library. Python 3.10 or later is recommended; no package installation or database server is required.

```powershell
python app.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The bundled CRM sample loads automatically. To use a different port, set `PORT` before starting the server.

## Ask questions

Try questions such as:

- What is the total sales?
- Which product has the highest revenue?
- Show monthly sales trends.
- Compare sales across categories.
- Which state has the lowest sales?
- How many orders are completed?
- What is the average sales by category?

The built-in interpreter answers common aggregations and grouping questions locally, without requiring an AI service. For questions it cannot interpret, configure an optional Gemini API key on the server. The question and column names/types are sent to Gemini for a restricted query plan; uploaded row values are never sent. All calculations, tables, and charts are generated locally from the dataset. If the AI service cannot interpret an unsupported question, the app shows the reason rather than fabricating a result.

### Optional Gemini setup

Set `GEMINI_API_KEY` in the server process environment, or add it to the existing project `.env` file:

```text
GEMINI_API_KEY=your-key
```

The default model is `gemini-3.8-flash`, matching the model used in the original CRM notebook. Optionally set `GEMINI_MODEL` to another model available to your API key. The key is read by Python, sent to Google from the local server, and never returned to the browser. Do not commit `.env` or paste a key into the notebook or frontend.

PowerShell example for one terminal session:

```powershell
$env:GEMINI_API_KEY = "your-key"
python app.py
```

The original CRM notebook also reads its MySQL credentials from environment variables (`MYSQL_PASSWORD`, and optionally `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, and `MYSQL_DATABASE`). Rotate credentials that were previously embedded in notebooks or shared.

## Data handling

- Upload CSV, XLSX, or JSON files up to 12 MB and 50,000 rows.
- CSV/Excel files use the first row as column names. JSON can be an array of row objects, or an object containing a `data` or `records` array.
- The app reports inferred column types, missing values, and duplicate rows, and shows a preview.
- The original uploaded bytes are kept unchanged in memory for download. Data and question history are cleared when the server restarts or another dataset is loaded.
- The server listens on `127.0.0.1` only. Uploaded data is not persisted to disk.
- Analysis history is kept in memory for the current server process; it is not a permanent archive.

## Results

Search and sort result tables, switch among relevant chart types, download results as CSV or Excel (`.xlsx`), and save charts as PNG. Open “How was this calculated?” to see the aggregation, grouping, filters, and matched-record count. Each answer names the source dataset and includes a dataset preview action.

## Project files

- `app.py` — local HTTP server, file readers, query interpretation, analysis, and exports.
- `static/` — responsive dashboard and browser interactions.
- `sample_crm_sales.csv` — example data based on the CRM seed records in `crm.sql`.
- `crm.sql` and `crm.ipynb` — the original CRM database and notebook materials.
