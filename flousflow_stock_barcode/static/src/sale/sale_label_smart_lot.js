import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { SaleLabelTextField } from "@sale/js/sale_label_text/sale_label_text";

const MIN_SCANNED_CODE_LENGTH = 12;
const MAX_SCANNER_KEY_GAP_MS = 80;

patch(SaleLabelTextField.prototype, {
    setup() {
        super.setup(...arguments);
        this.smartLotNotification = useService("notification");
        this.smartLotScanBuffer = "";
        this.smartLotScanFastKeys = 0;
        this.smartLotScanLastKeyAt = 0;
        this.smartLotScanPending = false;
    },

    onLabelInput(...args) {
        if (this.smartLotScanPending) {
            return;
        }
        return super.onLabelInput(...args);
    },

    async updateMany2XProduct(record) {
        let smartLotId = record.smartLotId;
        const scannedCode = this.getFirstLine(this.textareaRef()?.value).trim();
        if (!smartLotId && scannedCode.length >= MIN_SCANNED_CODE_LENGTH) {
            try {
                const result = await this.orm.call(
                    "product.template",
                    "resolve_sale_lot_scan",
                    [scannedCode]
                );
                if (result?.id === record.id) {
                    smartLotId = result.lot_id;
                }
            } catch {
                // Keep normal product selection working if Lot resolution is unavailable.
            }
        }
        await super.updateMany2XProduct(...arguments);
        await this.props.record.update({
            preferred_lot_id: smartLotId ? { id: smartLotId } : false,
        });
    },

    onLabelKeydown(ev) {
        if (ev.target !== this.textareaRef() || ev.ctrlKey || ev.metaKey || ev.altKey) {
            this._resetSmartLotScanBuffer();
            return super.onLabelKeydown(...arguments);
        }

        if (ev.key.length === 1) {
            const now = performance.now();
            const gap = now - this.smartLotScanLastKeyAt;
            if (this.smartLotScanLastKeyAt && gap <= MAX_SCANNER_KEY_GAP_MS) {
                this.smartLotScanBuffer += ev.key;
                this.smartLotScanFastKeys++;
            } else {
                this.smartLotScanBuffer = ev.key;
                this.smartLotScanFastKeys = 1;
            }
            this.smartLotScanLastKeyAt = now;
            return super.onLabelKeydown(...arguments);
        }

        if (ev.key === "Shift") {
            return super.onLabelKeydown(...arguments);
        }

        if (ev.key === "Enter") {
            const barcode = this.smartLotScanBuffer;
            const isScannerInput =
                barcode.length >= MIN_SCANNED_CODE_LENGTH &&
                this.smartLotScanFastKeys >= barcode.length - 2;
            this._resetSmartLotScanBuffer();

            if (isScannerInput) {
                ev.preventDefault();
                ev.stopImmediatePropagation();
                this.debouncedOnLabelInput.cancel();
                void this._resolveSmartLotBarcode(barcode);
                return;
            }
        }

        this._resetSmartLotScanBuffer();
        return super.onLabelKeydown(...arguments);
    },

    _resetSmartLotScanBuffer() {
        this.smartLotScanBuffer = "";
        this.smartLotScanFastKeys = 0;
        this.smartLotScanLastKeyAt = 0;
    },

    async _resolveSmartLotBarcode(barcode) {
        this.smartLotScanPending = true;
        try {
            const result = await this.orm.call(
                "product.template",
                "resolve_sale_lot_scan",
                [barcode]
            );
            if (!result) {
                this.smartLotNotification.add(
                    _t("No saleable product matches this Lot barcode."),
                    { type: "warning" }
                );
                this._restoreLineBreak();
                return;
            }
            await this.onMany2XUpdate([
                {
                    id: result.id,
                    display_name: result.display_name,
                    smartLotId: result.lot_id,
                },
            ]);
        } catch {
            this.smartLotNotification.add(
                _t("Could not look up the scanned Lot barcode."),
                { type: "danger" }
            );
            this._restoreLineBreak();
        } finally {
            this.smartLotScanPending = false;
        }
    },

    _restoreLineBreak() {
        const textarea = this.textareaRef();
        if (!textarea) {
            return;
        }
        const start = textarea.selectionStart ?? textarea.value.length;
        const end = textarea.selectionEnd ?? start;
        textarea.setRangeText("\n", start, end, "end");
        textarea.dispatchEvent(new InputEvent("input", { bubbles: true }));
    },
});
