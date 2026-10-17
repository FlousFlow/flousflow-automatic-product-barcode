# Smart Lot Barcode extensions (Odoo 20 Community)

This repository is distributed as one Odoo Apps module:
`flousflow_stock_barcode`. It includes product barcode generation, Inventory
Smart Lot workflows, and the POS bridge in one installable package.

The product barcode behavior remains backward compatible. Inventory and POS
support are included in the same module:

* the Inventory component depends on `stock` and adds the persistent
  `stock.lot.smart_barcode` field, company-scoped sequences, safe backfill,
  receipt/product/Lot printing actions, and Code 128 QWeb labels.
* the POS component depends on `point_of_sale` and resolves an `FFL-`
  Smart Lot scan to the native product and native lot name in one POS scan.

The manufacturer lot name (`stock.lot.name`) and product barcode are never
overwritten. A receipt action only processes actual assigned move-line lots; it
does not invent a physical batch split. Re-running generation is idempotent.

The POS bridge performs an authoritative server lookup for Smart Lot scans and
fails closed when the lookup is unavailable or the lot is outside the POS
company. Ordinary product, packaging, weight and price barcodes continue through
the native Odoo parser. Offline Smart Lot scanning is intentionally not claimed
as available until a deployment adds an approved local cache and server-side
reconciliation policy.

Install/update in Odoo 20 with the repository root on `addons_path`:

```bash
./odoo-bin -d <db> -u flousflow_stock_barcode --stop-after-init
```

Run the bridge tests with `--test-enable` on a clean Odoo 20 Community database.
