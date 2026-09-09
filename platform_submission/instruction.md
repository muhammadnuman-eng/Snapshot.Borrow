LumenStage already has production, performance, rehearsal, sound cue, role track, and prop records. The day pack brings this information together into one daily operational view for a production and date.

Only active records linked to the requested production through `metadata.production_id` should be included. Performances and rehearsals should be handled separately, and the production timezone should be used when valid; otherwise use UTC.

The day pack should save the production summary, performances, rehearsals, sound cues, role tracks, props, call timeline, gaps, and warnings.

Building the same production/date should keep the same pack ID and increase the version. The first build is version 1. Published packs are locked and cannot be rebuilt or published again.

Add API and CLI support for building, getting, listing, and publishing day packs. The API should support date/status filters, pagination, store revision information, and proper errors.

The call timeline starts 1 hour before each performance for all primary cast roles. Day packs are saved in the JSON store, so they are still available after the app is restarted.

IMPORTANT: Please work on this in a new branch from main and commit everything when you are done.
