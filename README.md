# RAPT Batches

Home Assistant custom integration that records fermentation batches from a RAPT Pill
(via the core RAPT Bluetooth integration) into its own SQLite file, so the recorder purge
never deletes your batch data. No RAPT cloud account needed.

**Requires Home Assistant 2025.3 or newer** (config subentries).

Fermentation data is kept in `config/rapt_batches.db`, not the recorder, so it survives the rolling purge.

## Install
1. Copy `custom_components/rapt_batches` into your HA `config/custom_components/`
   (or add this repo to HACS as a custom repository).
2. Restart HA, then Settings -> Devices & services -> Add integration -> RAPT Batches.
3. On the integration page choose **Start new batch** and follow the wizard.

## Use
- **Start new batch** (integration page): pick the Pill, check the detected sensors, set OG and start time.
  The form is prefilled with right-now values; overwrite them for a batch already underway
  (a past start time is backfilled from the recorder), or tick *Reset to current values*.
- **Lifecycle:** Active -> Finished -> Archived.
  - *Finish*: cog on the batch, tick *Finish batch* (or call `rapt_batches.stop_batch`). Recording stops, ABV locks to OG minus FG.
  - *Reopen*: cog on a finished batch, tick *Reopen*. Recording resumes and any gap is filled from the recorder.
  - *Archive*: cog on a finished batch, tick *Archive* (or use the panel). It leaves the integration page but stays in the panel.
  - Removing a batch from the integration page archives it; it never deletes data.
- **Brewing panel** (sidebar): list with Active / Finished / Archived filters, per-batch charts, notes, CSV export,
  compare up to 6 batches, unarchive, and delete (archived batches only).
- Each non-archived batch is a device with ABV, days fermenting and status sensors.

## Importing past batches
Brewing panel -> **Import**. Two sources:
- **Legacy RAPT Portal**: upload the CSV you exported from the old portal.
- **RAPT Brew website (brew.rapt.io)**: the new site has no export button, so the panel pulls a *finished*
  recording for you. Paste your RAPT login cookie, pick a recording from the list of everything on your account, and import.
  The dialog explains how to copy the cookie (easy on a computer, awkward on a phone). The cookie is treated like a
  password: it is used for that import only and never stored. Imports are admin only and land in Archived.

## Tests
`python -m unittest discover -s tests` (no Home Assistant install needed).

## Notes
- HA's date-time picker always shows a seconds field; the form defaults it to :00 and the integration ignores seconds.
- Charts use the bundled uPlot library (MIT); nothing is loaded from the internet.
