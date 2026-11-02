# integrator-rag

Exports Confluence Cloud pages to clean Markdown files for the Integrator RAG pilot.
Each file has YAML frontmatter (title, source URL, space, breadcrumb, labels, version, last updated)
so the RAG index can cite the original page. Re-runs are incremental: pages whose Confluence version
hasn't changed are skipped.

## Setup (Windows / PowerShell)

```powershell
cd C:\src\Testing\integrator-rag
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env   # then edit .env and paste your API token
```

Create the API token at https://id.atlassian.com/manage-profile/security/api-tokens.
The exporter only reads, and only sees pages your account can see.

## Usage

```powershell
# One page, by id or URL
python -m confluence_export --page 3390078977
python -m confluence_export --url "https://pdco-sw.atlassian.net/wiki/spaces/IE/pages/3390078977/Eaglesoft+Event+Writebacks+-+MVP+for+25.20"

# A page and everything under it
python -m confluence_export --tree 3390078977

# A whole space (cap it while testing)
python -m confluence_export --space IE --limit 50

# Options
#   --out DIR          output folder (default: output, or EXPORT_DIR in .env)
#   --force            re-export even if unchanged
#   --no-user-lookup   leave @mentions unresolved (fewer API calls)
#   -v                 verbose logging
```

Flags can be combined and repeated, e.g. `--space IE --tree 123 --page 456`.

## Output

```
output/
  .export-state.json                      # page id -> version + file (drives incremental runs)
  IE/
    eaglesoft-event-writebacks-mvp-for-25-20-3390078977.md
```

If a page is renamed, the old file is removed and a new one written.

### What converts and what doesn't

| Confluence | Markdown |
| --- | --- |
| Headings, lists, tables, bold/italic, links | Native Markdown |
| Code / noformat macros | Fenced code blocks with language |
| Info / note / warning / tip panels | `> **Note: title**` blockquotes |
| Expand sections | Bold title + content (always expanded) |
| Status lozenges | `[IN PROGRESS]` |
| Task lists | `- [x]` / `- [ ]` |
| @mentions | `@Display Name` |
| Jira macros | `[Jira: KEY-123]` (not the issue contents) |
| Images / attachments | `[image: name]` placeholder (content is lost) |
| Page includes | `[Included from page: Title]` (content not inlined) |
| TOC, children, page tree | Dropped |

## Tests

```powershell
pytest
```

## Next steps

- Upload `output/` to a Blob container and point an Azure AI Search / Foundry knowledge source at it.
- Swap the personal API token for a service account before running this on a schedule.
