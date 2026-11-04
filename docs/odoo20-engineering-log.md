# Odoo 20 Engineering Log

## 2026-11-04 — Smart Lot scanning and label layout

- Module: `flousflow_stock_barcode` 20.0.1.0.0.
- Request: resolve a scanned Smart Lot barcode to its product in Sales, preserve POS scanning, and correct malformed thermal label output.
- Evidence: repository review showed POS-only Smart Lot resolution; Sales product `name_search` did not resolve lot barcodes. The label report used 50x30 mm paper in Portrait, 2 mm margins, and a 220 px barcode.
- Changes: product exact-name lookup now resolves an accessible-company Smart Lot barcode under the active product-selection domain; label paper retains 50x30 mm Portrait dimensions with 1 mm margins and constrained content; POS retains its lot insertion path and applies Odoo's normal add-to-order eligibility check.
- Data integrity: sales quotations contain the product only. The actual Lot remains assigned on the stock delivery, preserving native Odoo tracking.
- Validation: full module suite ran on local Odoo 20 (37 tests, zero failures/errors). Sales barcode scan was simulated in the local browser and selected the product in the quotation line. This does not prove a physical scanner or thermal printer output.

## 2026-11-04 — Restore local Odoo 20 runtime

- The local test database had `stock_account` installed, but the sparse Odoo 20 source checkout omitted `addons/stock_account`. Its product view referenced `product.template.lot_valuated`, while the model field could not load, causing the browser parse error.
- Materialized the official `20.0` `stock_account` addon in the local Odoo source checkout and restarted Odoo against `codex_pos_fullflow_test`.
- Verified the Inventory product form opens and visibly renders the “Valuation by Lot/Serial” field. HTTP service remains on `127.0.0.1:8076`.
- This was a local Odoo source/runtime issue, not a change to the barcode module. Sales remains unavailable in this sparse checkout because the `sale` addon is absent.

## 2026-11-04 — Resolve Smart Lot scans on Sales Order lines

- Module: `flousflow_stock_barcode` 20.0.1.0.0.
- Evidence: the Odoo 20 Sales Order line uses `SaleLabelTextField`, which searches `product.template` from the description textarea. The existing Smart Lot lookup only extended `product.product`; the standard barcode plugin intentionally does not capture keystrokes inside editable fields, and the description widget debounces input before search.
- Change: resolve Smart Lot codes in `product.template.name_search` and handle fast scanner input ending in Enter in the Sales label field. A valid scan selects the saleable product; a miss keeps normal description entry and gives a warning.
- Scope: Sales quotations select the product while Odoo's stock delivery still assigns the actual Lot; POS resolution is unchanged.
- Validation: the module test suite passed on local Odoo 20 (37 tests, zero failures/errors). Browser simulation scanned `FFL-POS-FULLFLOW-LOT-PRODUCT-000075`; the Sales line displayed `FULL FLOW LOT SCAN TEST` with its configured price. No browser errors/warnings were recorded. A hardware scanner was not used.

## 2026-11-04 — Resolve Lot names scanned from the label

- Reproduction: existing quotation `S00001` contained `FFL-POS-FULLFLOW-LOT-PRODUCT-000002` as plain description text. In the local database, that value was `stock.lot.name`; its distinct `smart_barcode` ended in `000075`.
- Change: Sales and product name search now resolve either exact `stock.lot.name` or `stock.lot.smart_barcode`. If one scanned name matches different products, lookup returns no product instead of guessing.
- Validation: full module suite passed (37 tests, zero failures/errors). Browser scan simulation of the exact failing value `FFL-POS-FULLFLOW-LOT-PRODUCT-000002` selected `FULL FLOW LOT SCAN TEST`; the displayed line populated its configured price and tax.

## 2026-11-04 — Match scanner output with a missing leading prefix

- Reproduction: confirmed order `S00002` stored `FULLFLOW-LOT-PRODUCT-000002` (plus the Enter newline) as its description, with no product selected. The matching Lot name in the same database was `FFL-POS-FULLFLOW-LOT-PRODUCT-000002`.
- Change: if no exact Lot name or Smart Lot barcode exists, allow a suffix match of at least 12 characters, scoped to accessible companies and accepted only when it resolves to one product. Ambiguous matches still fail closed.
- Validation: full module suite passed (37 tests, zero failures/errors). Browser simulation of the exact string stored on `S00002` selected `FULL FLOW LOT SCAN TEST` and populated its configured price and tax.

## 2026-11-04 — Carry scanned Sales Lot into delivery reservation

- Request: when an operator scans a Lot on a Sales Order, reserve that same Lot for its delivery; if it is short, use its available quantity and backorder the remainder.
- Evidence: Odoo 20 core `stock.move._action_assign`, `lot_ids` inverse, and `stock.quant` reservation APIs were inspected. The prior Sales scan resolved only the product, allowing normal FIFO reservation to pick a different Lot.
- Change: Sales scan now returns the exact accessible Lot alongside the saleable product, persists it on the Sales Order Line, and overrides only the stock reservation step for those linked moves. Standard unscanned orders keep Odoo's normal removal strategy. For a scanned Lot shortage, other Lots are not substituted.
- Validation: full addon suite passed on local Odoo 20 (39 tests, zero failures/errors), including full and partial Lot reservation/backorder cases. Browser flow scanned `FULLFLOW-LOT-PRODUCT-000002`, created `S00005`, and showed 10 units from Lot `FFL-POS-FULLFLOW-LOT-PRODUCT-000002` on `WH/OUT/00003`; the transfer was validated. Database confirms the transfer is Done and its 10-unit move line has Lot id 86. This is local test-database evidence; no physical scanner was used.

## 2026-11-04 — Retain Lot when Sales autocomplete handles the scan

- Reproduction: confirmed `S00006` had no `preferred_lot_id` on its Sales Order Line, so Odoo's default FIFO reserved 5 units from Lot `LOT-FULLFLOW-2026`. The scanner text had matched the product through Sales autocomplete without carrying the Lot identity into the line.
- Change: when Sales selects a product, resolve the first line of the current description against accessible Lot codes if the direct fast-scanner path did not attach a Lot. Preserve regular product selection if lookup fails. Module version advanced to `20.0.1.0.1`.
- Validation: module suite passed again (39 tests, zero failures/errors). Browser pasted Lot name `FFL-POS-FULLFLOW-LOT-PRODUCT-000002`, chose the product from autocomplete, saved `S00007` with preferred Lot 86, confirmed the order, and validated `WH/OUT/00005`; database confirms its completed 1-unit move used that exact Lot. `S00006` remains untouched because its scanned Lot was not recorded and cannot be reconstructed safely from the confirmed order.
