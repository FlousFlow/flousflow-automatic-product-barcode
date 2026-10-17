# Flous Flow Stock Barcode

Automatically generate unique barcodes for products and variants.

| | |
|---|---|
| **Version** | 20.0.1.0.0 |
| **License** | LGPL-3 |
| **Dependencies** | `product` |
| **Compatibility** | Odoo 20 Community & Enterprise, self-hosted, Odoo.sh |

## Overview

This module assigns a unique barcode to every new `product.product` variant
whose `barcode` field is empty, using the native Odoo `ir.sequence` for
concurrency-safe numbering. Administrators can also fill barcodes on existing
products retroactively.

The barcode is always assigned on `product.product.barcode`. No custom barcode
field is created, and `product.template` is never given an independent value.

## Installation

1. Copy the `flousflow_stock_barcode` folder into an addons path.
2. Install the "Flous Flow Stock Barcode" module from the Apps menu.
3. Upgrade with the standard command:

```bash
./odoo-bin -c odoo.conf -d <database> -u flousflow_stock_barcode
```

Installation does **not** modify existing products. Barcodes are only
generated after the feature is enabled or after an explicit user action.

## Configuration

Open **Settings -> Automatic Product Barcodes**:

- **Enable Automatic Barcode Generation** — turn the feature on or off.
- **Barcode Format** — Sequential Numeric, Prefix + Sequential Numeric, or EAN-13.
- **Prefix** — optional prefix prepended to the generated number.
- **Sequence Digits** — length of the sequential part.
- **Starting Number** — first number to generate.
- **Barcode Preview** — live preview of the next value.
- **Existing Barcode Policy** — always "Keep Existing Barcodes" in V1.
- **Include Archived Products** — whether retroactive generation includes archived variants.

Each company has its own configuration and its own independent sequence.

### EAN-13

- The check digit is computed according to the EAN-13 algorithm.
- For EAN-13, the prefix length plus the sequence length must equal 12 digits
  (a 13th check digit is appended). An invalid combination raises a
  `ValidationError` instead of silently truncating.
- Generated EAN-13 numbers are internal identifiers unless the company owns an
  appropriate GS1 prefix.

## Automatic generation

When enabled, a new `product.product` variant receives a barcode only if its
`barcode` field is empty. Explicitly entered or imported barcodes are never
modified. This covers simple products, products with variants, variants added
after template creation, and duplicated products.

## Existing products

Use the **Generate Missing Barcodes** button in Settings (opens the wizard) or
the **Generate Missing Barcodes** contextual action in the Product Variants
list. Both process only `product.product` records with an empty barcode.

## Product variants

Every variant is a `product.product` record, so each one receives its own
unique barcode through the same mechanism.

## Multi-company

Each company configures its own enabled state, prefix, format and sequence.
Configuration is never shared between companies, and a multi-company record
rule isolates the configuration records.

## Known limitations

- Replacing existing barcodes is not supported in V1 (existing barcodes are
  always preserved).
- The contextual action requires a saved configuration for the company of the
  selected products.
- EAN-13 values are internal identifiers, not official GS1 GTINs.

## Uninstallation

Uninstalling the module never deletes or resets product barcode values.
Barcodes are ordinary product data and remain untouched.

## FAQ

- **Will the module overwrite my existing product barcodes?**
  No. Existing barcodes are preserved.
- **Does it support product variants?**
  Yes. Each product variant receives its own barcode.
- **Can it generate barcodes for products created before installation?**
  Yes. Use the Generate Missing Barcodes wizard.
- **Does it work with Odoo Online SaaS?**
  No. Odoo Online does not support normal third-party Python addons.
- **Are generated EAN-13 values automatically official GS1 GTIN numbers?**
  No. A company must use its valid GS1 allocation if official trade
  identification numbers are required.

## Tests

Automated tests cover automatic generation, variants, new variants, existing
barcode preservation, enable/disable, re-enable, the retroactive wizard,
archived products, multi-company isolation, collision handling, EAN-13
generation and validation, the contextual action, and uninstall behavior.
