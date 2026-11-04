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
