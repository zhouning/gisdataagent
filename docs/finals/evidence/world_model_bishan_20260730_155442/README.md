# Bishan county planning evidence snapshot

Source run: `/app/data_agent/uploads/admin/world_model_v21/20260730_155442_050986`

- `mpc_summary.json`: unmodified planning summary copied from the finals container.
- `paper9_agent_audit.json`: unmodified hard-gate audit copied from the same run.
- `optimized_changes.geojson`: the `CHG_FLAG != 0` features extracted from the run's
  `optimized_dltb.fgb`; the finals deck uses the existing same-snapshot county geometry
  as the unchanged background.

The live run returned 406 farmland-to-forest features and 406 forest-to-farmland
features. The deck generator validates these counts against `swaps_completed` before
building the presentation.
