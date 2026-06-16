# Genre Knowledge Import Guide

Use `Genre_Knowledge_Import_Template.xlsx` as the blank/source template for human research.
Use `Genre_Knowledge_Real_World_Seed.xlsx` when you want to import the prefilled real-world examples.

## What The Researcher Should Fill

The researcher mainly fills:

- `04_Reference_Videos`: one row for each watched YouTube Short.
- `05_Script_Analysis`: one row for the same video URL after watching and analyzing it.
- `08_Topic_Research_Sources`: real-world source links and extracted facts for grounded topic generation.

The researcher can read:

- `00_Column_Explanations`: plain-English meaning of every column in every sheet.
- `09_Field_Rules`: required fields, data types, max lengths, allowed values, and examples.
- `10_Playground_Test_Topics`: internet-sourced test topics you can paste into the playground app.

The importer ignores `00_Column_Explanations`, `README`, `09_Field_Rules`, and `10_Playground_Test_Topics`, so you do not need to remove those sheets before importing.

The owner/admin usually maintains:

- `01_Genres`
- `02_Genre_Rules`
- `03_Genre_Hooks`
- `06_Visual_Style_Rules`
- `07_Topic_Expansion_Rules`

## Most Important Columns

For each video, fill these well:

- `genre_id`
- `video_url`
- `title`
- `full_script`
- `views`
- `duration_sec`
- `hook_first_sentence`
- `hook_type`
- `hook_emotional_trigger`
- `narrative_technique`
- `emotional_arc`
- `twist_line`
- `ending_type`
- `retention_hook`
- `likely_share_trigger`
- `why_it_worked`
- `what_to_improve`

## Data Rules

All length/type restrictions are listed in the workbook sheet `09_Field_Rules`.

Important rules:

- Do not rename sheets.
- Do not rename column headers.
- Dates must use `YYYY-MM-DD`.
- Number columns must contain only numbers.
- Boolean columns accept `TRUE/FALSE`, `YES/NO`, or `1/0`.
- `genre_id` must match `01_Genres.id`.
- `05_Script_Analysis.video_url` must match `04_Reference_Videos.video_url`.

## Generate A Fresh Template

From `DesktopApp/backend`:

```bash
python3 tools/genre_knowledge.py template
```

## Generate The Prefilled Real-World Seed Workbook

From `DesktopApp/backend`:

```bash
python3 tools/genre_knowledge.py examples
```

## Back Up And Clear Genre Knowledge Tables

This clears only the normalized genre knowledge tables. It does not clear users, API keys, chats, or video jobs.

```bash
python3 tools/genre_knowledge.py reset --backup
```

## Import A Filled Workbook

```bash
python3 tools/genre_knowledge.py import data/knowledge/Genre_Knowledge_Import_Template.xlsx --backup --reset
```

To import the prefilled real-world examples instead:

```bash
python3 tools/genre_knowledge.py import data/knowledge/Genre_Knowledge_Real_World_Seed.xlsx --backup --reset
```

Use `--reset` when the workbook should replace existing knowledge data.
Omit `--reset` when the workbook should update/add rows without clearing first.

Backups are written to:

```text
data/knowledge/backups/
```
