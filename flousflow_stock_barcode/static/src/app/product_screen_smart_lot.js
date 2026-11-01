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
        // Odoo 20 invokes barcode callbacks without a component context.
        useBarcodeReader({ smart_lot: this._barcodeSmartLotAction.bind(this) });
    },

    async _barcodeSmartLotAction(code) {
        const raw = typeof code === "string" ? code : code?.code || code?.base_code || "";
        let lot;
        try {
            lot = await this.pos.data.call(
                "stock.lot",
                "pos_resolve_smart_barcode",
                [raw, this.pos.company.id]
            );
        } catch {
            this.notification.add(_t("Smart Lot lookup is unavailable. The scan was rejected."), { type: "danger" });
            return true;
        }
        if (!lot) {
            return false;
        }
        const productId = lot.product_id;
        let product = this.pos.models["product.product"].get(productId);
        if (!product) {
            await this.pos.loadNewProducts([["id", "=", lot.product_tmpl_id]]);
            product = this.pos.models["product.product"].get(productId);
        }
        if (!product) {
            this.notification.add(_t("The product for this Smart Lot is not available in this POS."), { type: "danger" });
            return true;
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
