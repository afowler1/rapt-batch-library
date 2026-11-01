# RAPT Batches

Home Assistant custom integration that records fermentation batches from a RAPT Pill
(via the core RAPT Bluetooth integration) into its own SQLite file, so the recorder purge
never deletes your batch data. No RAPT cloud account needed.

**Requires Home Assistant 2025.3 or newer** (config subentries).

## Install
1. Copy `custom_components/rapt_batches` into your HA `config/custom_components/`
   (or add this repo to HACS as a custom repository).
2. Restart HA, then Settings -> Devices & services -> Add integration -> RAPT Batches.
3. On the integration page choose **Start new batch** and follow the wizard.

## Use
- **Start new batch:** pick the Pill, check the detected sensors, set OG and start time.
  A past start time is backfilled from the recorder history.
- **Finish a batch:** on the batch, choose *Edit or finish batch*, tick *Finish batch*,
  optionally enter FG. Or call the `rapt_batches.stop_batch` service.
- Each batch gets a device with ABV, days fermenting and status sensors.
- Data lives in `config/rapt_batches.db` (included in HA backups).
