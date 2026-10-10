/** Resolve Smart Lot barcodes before native product barcode fallback. */
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { useBarcodeReader } from "@point_of_sale/app/hooks/barcode_reader_hook";
import { BarcodeReader } from "@point_of_sale/app/services/barcode_reader_service";

patch(BarcodeReader.prototype, {
    async _scan(code) {
        if (typeof code === "string") {
            const cbMaps = this.exclusiveCbMap ? [this.exclusiveCbMap] : [...this.cbMaps];
            const callbacks = cbMaps.map((cbMap) => cbMap.smart_lot).filter(Boolean);
            for (const callback of callbacks) {
                const handled = await callback({ type: "smart_lot", code, base_code: code, value: 0 });
                if (handled) {
                    return;
                }
            }
        }
        return super._scan(...arguments);
    },
});

patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
        useBarcodeReader({ smart_lot: this._barcodeSmartLotAction });
    },

    async _barcodeProductAction(code) {
        const lotLine = await this._barcodeSmartLotAction(code, { silent: true });
        if (lotLine) {
            return lotLine;
        }
        return super._barcodeProductAction(...arguments);
    },

    async _barcodeSmartLotAction(code, options = {}) {
        const raw = code?.code || code?.base_code || "";
        let rows;
        try {
            rows = await this.pos.data.searchRead(
                "stock.lot",
                [["smart_barcode", "=", raw], ["company_id", "=", this.pos.company.id]],
                ["id", "name", "product_id", "smart_barcode"]
            );
        } catch {
            if (!options.silent) {
                this.notification.add(_t("Smart Lot lookup is unavailable. The scan was rejected."), { type: "danger" });
            }
            return false;
        }
        const lot = rows?.[0];
        if (!lot) {
            if (!options.silent) {
                this.notification.add(_t("The Smart Lot Barcode is unknown or belongs to another company."), { type: "danger" });
            }
            return false;
        }
        const productId = Array.isArray(lot.product_id) ? lot.product_id[0] : lot.product_id;
        let product = this.pos.models["product.product"].get(productId);
        if (!product) {
            await this.pos.loadNewProducts([["id", "=", productId]]);
            product = this.pos.models["product.product"].get(productId);
        }
        if (!product) {
            this.notification.add(_t("The product for this Smart Lot is not available in this POS."), { type: "danger" });
            return false;
        }
        this.sound.play("beep");
        const line = await this.pos.addLineToCurrentOrder(
            { product_id: product, product_tmpl_id: product.product_tmpl_id },
            { code: { type: "lot", code: lot.name }, merge: false },
            product.needToConfigure()
        );
        this.numberBuffer.reset();
        return line;
    },
});
